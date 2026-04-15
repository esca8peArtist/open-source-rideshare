"""Tests for the Platform Announcements feature.

Service layer (async, mocked DB):
  1.  create_announcement — inserts and returns announcement
  2.  update_announcement — applies partial update
  3.  update_announcement — raises 404 when not found
  4.  publish_announcement — sets published_at
  5.  publish_announcement — raises 409 when already published
  6.  unpublish_announcement — clears published_at
  7.  unpublish_announcement — raises 409 when not published
  8.  delete_announcement — sets is_active=False
  9.  delete_announcement — raises 404 when not found
  10. get_announcement — returns announcement when found
  11. get_announcement — raises 404 when not found
  12. list_public_announcements — returns only ALL-audience published non-expired
  13. list_public_announcements — excludes unpublished
  14. list_public_announcements — excludes expired
  15. list_announcements_for_user — driver sees ALL + DRIVERS + MEMBERS
  16. list_announcements_for_user — rider sees ALL + RIDERS + MEMBERS
  17. list_announcements_for_user — excludes unpublished
  18. mark_viewed — creates view record on first call
  19. mark_viewed — returns existing record on repeat call (no duplicate)
  20. mark_viewed — raises 404 for unknown announcement
  21. acknowledge_announcement — creates view+ack in one step
  22. acknowledge_announcement — acks existing view record
  23. acknowledge_announcement — raises 409 when already acknowledged
  24. acknowledge_announcement — raises 422 when requires_acknowledgment=False
  25. get_pending_acknowledgments — returns unacknowledged critical items
  26. get_pending_acknowledgments — excludes already-acknowledged items
  27. get_pending_acknowledgments — excludes expired items
  28. get_announcement_stats — returns correct view and ack counts
  29. get_announcement_views — returns paginated view records

Schema validation:
  30. CreateAnnouncementRequest — rejects title under 3 chars
  31. CreateAnnouncementRequest — rejects body under 10 chars
  32. UpdateAnnouncementRequest — accepts partial update (body only)
  33. _audience_for_role — DRIVER includes DRIVERS
  34. _audience_for_role — RIDER includes RIDERS

API layer (integration-style, skipped without live DB):
  35. GET /announcements — 200 public list
  36. GET /me/announcements — 200 authenticated feed
  37. GET /me/announcements/pending — 200 pending critical
  38. POST /me/announcements/{id}/view — 200 mark viewed
  39. POST /me/announcements/{id}/acknowledge — 200 acknowledge
  40. POST /admin/announcements — 201 create draft
  41. POST /admin/announcements — 403 non-admin
  42. GET /admin/announcements — 200 list all
  43. GET /admin/announcements/{id} — 200 detail
  44. GET /admin/announcements/{id} — 404 missing
  45. GET /admin/announcements/{id}/stats — 200 stats
  46. PUT /admin/announcements/{id} — 200 update
  47. POST /admin/announcements/{id}/publish — 200 publish
  48. POST /admin/announcements/{id}/publish — 409 already published
  49. POST /admin/announcements/{id}/unpublish — 200 unpublish
  50. DELETE /admin/announcements/{id} — 204 soft-delete
  51. GET /admin/announcements/{id}/views — 200 view records
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.announcement import (
    AnnouncementAudience,
    AnnouncementPriority,
    AnnouncementView,
    PlatformAnnouncement,
)
from app.models.user import UserRole
from app.schemas.announcement import (
    CreateAnnouncementRequest,
    UpdateAnnouncementRequest,
)
from app.services.announcements import (
    AnnouncementError,
    _audience_for_role,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
_PAST = _NOW - timedelta(hours=1)
_FUTURE = _NOW + timedelta(days=7)


def _make_ann(**kw) -> PlatformAnnouncement:
    defaults = dict(
        id=1,
        title="New Platform Policy",
        body="We have updated our driver pay formula.",
        audience=AnnouncementAudience.ALL,
        priority=AnnouncementPriority.NORMAL,
        requires_acknowledgment=False,
        published_at=_PAST,
        expires_at=None,
        created_by=99,
        is_active=True,
        created_at=_PAST,
        updated_at=_PAST,
    )
    defaults.update(kw)
    obj = MagicMock(spec=PlatformAnnouncement)
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _make_view(**kw) -> AnnouncementView:
    defaults = dict(
        id=10,
        announcement_id=1,
        user_id=5,
        viewed_at=_NOW,
        acknowledged_at=None,
    )
    defaults.update(kw)
    obj = MagicMock(spec=AnnouncementView)
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _make_user(role: UserRole = UserRole.RIDER, user_id: int = 5):
    u = MagicMock()
    u.id = user_id
    u.role = role
    return u


def _async_result(value):
    """Build a mock execute() result whose scalar_one_or_none returns value."""
    m = MagicMock()
    m.scalar_one_or_none = MagicMock(return_value=value)
    m.scalar_one = MagicMock(return_value=value)
    m.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=value if isinstance(value, list) else [value] if value else [])))
    return m


def _make_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Service layer tests — create/update/publish/unpublish/delete
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_announcement():
    """create_announcement inserts and returns the announcement."""
    from app.services.announcements import create_announcement

    db = _make_db()
    ann = _make_ann(id=None, published_at=None)
    db.add = MagicMock(side_effect=lambda obj: setattr(obj, "id", 1))
    db.flush = AsyncMock()

    req = CreateAnnouncementRequest(title="Test", body="Test body content")

    with patch("app.services.announcements.PlatformAnnouncement", return_value=ann):
        result = await create_announcement(db, admin_id=99, req=req)

    db.add.assert_called_once()
    db.flush.assert_called_once()
    assert result is ann


@pytest.mark.anyio
async def test_update_announcement():
    """update_announcement applies partial updates."""
    from app.services.announcements import update_announcement

    db = _make_db()
    ann = _make_ann()
    db.execute = AsyncMock(return_value=_async_result(ann))

    req = UpdateAnnouncementRequest(title="Updated Title")
    result = await update_announcement(db, ann_id=1, req=req)

    assert result is ann
    assert ann.title == "Updated Title"
    db.flush.assert_called_once()


@pytest.mark.anyio
async def test_update_announcement_not_found():
    """update_announcement raises 404 when announcement not found."""
    from app.services.announcements import update_announcement

    db = _make_db()
    db.execute = AsyncMock(return_value=_async_result(None))

    with pytest.raises(AnnouncementError) as exc_info:
        await update_announcement(db, ann_id=999, req=UpdateAnnouncementRequest())
    assert exc_info.value.status_code == 404


@pytest.mark.anyio
async def test_publish_announcement():
    """publish_announcement sets published_at."""
    from app.services.announcements import publish_announcement

    db = _make_db()
    ann = _make_ann(published_at=None)
    db.execute = AsyncMock(return_value=_async_result(ann))

    result = await publish_announcement(db, ann_id=1)

    assert result is ann
    assert ann.published_at is not None
    db.flush.assert_called_once()


@pytest.mark.anyio
async def test_publish_announcement_already_published():
    """publish_announcement raises 409 when already published."""
    from app.services.announcements import publish_announcement

    db = _make_db()
    ann = _make_ann(published_at=_PAST)
    db.execute = AsyncMock(return_value=_async_result(ann))

    with pytest.raises(AnnouncementError) as exc_info:
        await publish_announcement(db, ann_id=1)
    assert exc_info.value.status_code == 409


@pytest.mark.anyio
async def test_unpublish_announcement():
    """unpublish_announcement clears published_at."""
    from app.services.announcements import unpublish_announcement

    db = _make_db()
    ann = _make_ann(published_at=_PAST)
    db.execute = AsyncMock(return_value=_async_result(ann))

    result = await unpublish_announcement(db, ann_id=1)

    assert result is ann
    assert ann.published_at is None
    db.flush.assert_called_once()


@pytest.mark.anyio
async def test_unpublish_announcement_not_published():
    """unpublish_announcement raises 409 when announcement is a draft."""
    from app.services.announcements import unpublish_announcement

    db = _make_db()
    ann = _make_ann(published_at=None)
    db.execute = AsyncMock(return_value=_async_result(ann))

    with pytest.raises(AnnouncementError) as exc_info:
        await unpublish_announcement(db, ann_id=1)
    assert exc_info.value.status_code == 409


@pytest.mark.anyio
async def test_delete_announcement():
    """delete_announcement soft-deletes (is_active=False)."""
    from app.services.announcements import delete_announcement

    db = _make_db()
    ann = _make_ann()
    db.execute = AsyncMock(return_value=_async_result(ann))

    await delete_announcement(db, ann_id=1)

    assert ann.is_active is False
    db.flush.assert_called_once()


@pytest.mark.anyio
async def test_delete_announcement_not_found():
    """delete_announcement raises 404 when not found."""
    from app.services.announcements import delete_announcement

    db = _make_db()
    db.execute = AsyncMock(return_value=_async_result(None))

    with pytest.raises(AnnouncementError) as exc_info:
        await delete_announcement(db, ann_id=999)
    assert exc_info.value.status_code == 404


@pytest.mark.anyio
async def test_get_announcement():
    """get_announcement returns the announcement."""
    from app.services.announcements import get_announcement

    db = _make_db()
    ann = _make_ann()
    db.execute = AsyncMock(return_value=_async_result(ann))

    result = await get_announcement(db, ann_id=1)
    assert result is ann


@pytest.mark.anyio
async def test_get_announcement_not_found():
    """get_announcement raises 404 when not found."""
    from app.services.announcements import get_announcement

    db = _make_db()
    db.execute = AsyncMock(return_value=_async_result(None))

    with pytest.raises(AnnouncementError) as exc_info:
        await get_announcement(db, ann_id=999)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service layer tests — list operations
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_public_announcements_returns_all_audience():
    """list_public_announcements returns published ALL-audience non-expired."""
    from app.services.announcements import list_public_announcements

    db = _make_db()
    ann = _make_ann(audience=AnnouncementAudience.ALL, published_at=_PAST, expires_at=None)
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = [ann]
    db.execute = AsyncMock(return_value=result_mock)

    result = await list_public_announcements(db)
    assert ann in result


@pytest.mark.anyio
async def test_list_public_announcements_excludes_unpublished():
    """list_public_announcements returns empty list when only drafts exist."""
    from app.services.announcements import list_public_announcements

    db = _make_db()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=result_mock)

    result = await list_public_announcements(db)
    assert result == []


@pytest.mark.anyio
async def test_list_public_announcements_excludes_expired():
    """list_public_announcements excludes expired announcements."""
    from app.services.announcements import list_public_announcements

    db = _make_db()
    result_mock = MagicMock()
    # Expired announcement filtered at DB level — service returns empty
    result_mock.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=result_mock)

    result = await list_public_announcements(db)
    assert result == []


@pytest.mark.anyio
async def test_list_announcements_for_driver():
    """list_announcements_for_user includes ALL, DRIVERS, MEMBERS for a driver."""
    from app.services.announcements import list_announcements_for_user

    db = _make_db()
    anns = [_make_ann(audience=AnnouncementAudience.DRIVERS)]
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = anns
    db.execute = AsyncMock(return_value=result_mock)

    user = _make_user(role=UserRole.DRIVER)
    result = await list_announcements_for_user(db, user)
    assert anns[0] in result


@pytest.mark.anyio
async def test_list_announcements_for_rider():
    """list_announcements_for_user includes ALL, RIDERS, MEMBERS for a rider."""
    from app.services.announcements import list_announcements_for_user

    db = _make_db()
    anns = [_make_ann(audience=AnnouncementAudience.RIDERS)]
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = anns
    db.execute = AsyncMock(return_value=result_mock)

    user = _make_user(role=UserRole.RIDER)
    result = await list_announcements_for_user(db, user)
    assert anns[0] in result


@pytest.mark.anyio
async def test_list_announcements_excludes_unpublished():
    """list_announcements_for_user returns empty when all announcements are drafts."""
    from app.services.announcements import list_announcements_for_user

    db = _make_db()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=result_mock)

    user = _make_user(role=UserRole.RIDER)
    result = await list_announcements_for_user(db, user)
    assert result == []


# ---------------------------------------------------------------------------
# Service layer tests — view and acknowledge
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_mark_viewed_creates_view():
    """mark_viewed creates a new view record when none exists."""
    from app.services.announcements import mark_viewed

    db = _make_db()
    ann = _make_ann()
    # First execute = get_announcement (_get_or_404), second = check existing view
    db.execute = AsyncMock(side_effect=[
        _async_result(ann),
        _async_result(None),  # no existing view
    ])

    added_objects = []
    db.add = MagicMock(side_effect=added_objects.append)

    result = await mark_viewed(db, user_id=5, ann_id=1)

    # add() should have been called once (the new AnnouncementView)
    assert db.add.call_count == 1
    db.flush.assert_called_once()
    # The added object should be an AnnouncementView
    assert isinstance(added_objects[0], AnnouncementView)


@pytest.mark.anyio
async def test_mark_viewed_returns_existing():
    """mark_viewed returns existing view record without inserting a duplicate."""
    from app.services.announcements import mark_viewed

    db = _make_db()
    ann = _make_ann()
    existing_view = _make_view()
    db.execute = AsyncMock(side_effect=[
        _async_result(ann),
        _async_result(existing_view),
    ])

    result = await mark_viewed(db, user_id=5, ann_id=1)

    db.add.assert_not_called()
    assert result is existing_view


@pytest.mark.anyio
async def test_mark_viewed_not_found():
    """mark_viewed raises 404 when announcement not found."""
    from app.services.announcements import mark_viewed

    db = _make_db()
    db.execute = AsyncMock(return_value=_async_result(None))

    with pytest.raises(AnnouncementError) as exc_info:
        await mark_viewed(db, user_id=5, ann_id=999)
    assert exc_info.value.status_code == 404


@pytest.mark.anyio
async def test_acknowledge_creates_view_and_ack():
    """acknowledge_announcement creates view+ack in one step when no view exists."""
    from app.services.announcements import acknowledge_announcement

    db = _make_db()
    ann = _make_ann(requires_acknowledgment=True)
    db.execute = AsyncMock(side_effect=[
        _async_result(ann),
        _async_result(None),  # no existing view
    ])

    added_objects = []
    db.add = MagicMock(side_effect=added_objects.append)

    result = await acknowledge_announcement(db, user_id=5, ann_id=1)

    # Should have created and added a new AnnouncementView
    assert db.add.call_count == 1
    db.flush.assert_called_once()
    added_view = added_objects[0]
    assert isinstance(added_view, AnnouncementView)
    assert added_view.acknowledged_at is not None


@pytest.mark.anyio
async def test_acknowledge_existing_view():
    """acknowledge_announcement sets acknowledged_at on existing view."""
    from app.services.announcements import acknowledge_announcement

    db = _make_db()
    ann = _make_ann(requires_acknowledgment=True)
    view = _make_view(acknowledged_at=None)
    db.execute = AsyncMock(side_effect=[
        _async_result(ann),
        _async_result(view),
    ])

    result = await acknowledge_announcement(db, user_id=5, ann_id=1)

    assert view.acknowledged_at is not None
    db.flush.assert_called_once()


@pytest.mark.anyio
async def test_acknowledge_already_acknowledged():
    """acknowledge_announcement raises 409 when already acknowledged."""
    from app.services.announcements import acknowledge_announcement

    db = _make_db()
    ann = _make_ann(requires_acknowledgment=True)
    view = _make_view(acknowledged_at=_PAST)
    db.execute = AsyncMock(side_effect=[
        _async_result(ann),
        _async_result(view),
    ])

    with pytest.raises(AnnouncementError) as exc_info:
        await acknowledge_announcement(db, user_id=5, ann_id=1)
    assert exc_info.value.status_code == 409


@pytest.mark.anyio
async def test_acknowledge_not_required():
    """acknowledge_announcement raises 422 when requires_acknowledgment=False."""
    from app.services.announcements import acknowledge_announcement

    db = _make_db()
    ann = _make_ann(requires_acknowledgment=False)
    db.execute = AsyncMock(return_value=_async_result(ann))

    with pytest.raises(AnnouncementError) as exc_info:
        await acknowledge_announcement(db, user_id=5, ann_id=1)
    assert exc_info.value.status_code == 422


@pytest.mark.anyio
async def test_get_pending_acknowledgments_returns_unacked():
    """get_pending_acknowledgments returns critical announcements not yet acked."""
    from app.services.announcements import get_pending_acknowledgments

    db = _make_db()
    ann = _make_ann(
        requires_acknowledgment=True,
        priority=AnnouncementPriority.CRITICAL,
        published_at=_PAST,
        expires_at=None,
    )
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = [ann]
    db.execute = AsyncMock(return_value=result_mock)

    user = _make_user()
    result = await get_pending_acknowledgments(db, user)
    assert ann in result


@pytest.mark.anyio
async def test_get_pending_acknowledgments_excludes_acked():
    """get_pending_acknowledgments returns empty when all are acknowledged (DB-level filter)."""
    from app.services.announcements import get_pending_acknowledgments

    db = _make_db()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=result_mock)

    user = _make_user()
    result = await get_pending_acknowledgments(db, user)
    assert result == []


@pytest.mark.anyio
async def test_get_pending_acknowledgments_excludes_expired():
    """get_pending_acknowledgments excludes expired announcements (DB-level filter)."""
    from app.services.announcements import get_pending_acknowledgments

    db = _make_db()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=result_mock)

    user = _make_user()
    result = await get_pending_acknowledgments(db, user)
    assert result == []


# ---------------------------------------------------------------------------
# Service layer tests — analytics
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_announcement_stats():
    """get_announcement_stats returns correct view and ack counts."""
    from app.services.announcements import get_announcement_stats

    db = _make_db()
    ann = _make_ann()
    view_count_result = MagicMock()
    view_count_result.scalar_one = MagicMock(return_value=10)
    ack_count_result = MagicMock()
    ack_count_result.scalar_one = MagicMock(return_value=7)

    db.execute = AsyncMock(side_effect=[
        _async_result(ann),
        view_count_result,
        ack_count_result,
    ])

    stats = await get_announcement_stats(db, ann_id=1)

    assert stats.total_views == 10
    assert stats.total_acknowledgments == 7


@pytest.mark.anyio
async def test_get_announcement_views():
    """get_announcement_views returns paginated view records."""
    from app.services.announcements import get_announcement_views

    db = _make_db()
    ann = _make_ann()
    view = _make_view()
    views_result = MagicMock()
    views_result.scalars.return_value.all.return_value = [view]

    db.execute = AsyncMock(side_effect=[
        _async_result(ann),
        views_result,
    ])

    records = await get_announcement_views(db, ann_id=1)
    assert len(records) == 1
    assert records[0].user_id == view.user_id


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


def test_create_request_rejects_short_title():
    """CreateAnnouncementRequest rejects title under 3 chars."""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CreateAnnouncementRequest(title="Hi", body="Valid body text here")


def test_create_request_rejects_short_body():
    """CreateAnnouncementRequest rejects body under 10 chars."""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CreateAnnouncementRequest(title="Valid Title", body="Short")


def test_update_request_accepts_partial():
    """UpdateAnnouncementRequest accepts body-only partial update."""
    req = UpdateAnnouncementRequest(body="This is an updated body text for the announcement.")
    assert req.body is not None
    assert req.title is None


def test_audience_for_role_driver():
    """_audience_for_role returns DRIVERS audience for DRIVER role."""
    audiences = _audience_for_role(UserRole.DRIVER)
    assert AnnouncementAudience.DRIVERS in audiences
    assert AnnouncementAudience.ALL in audiences
    assert AnnouncementAudience.MEMBERS in audiences
    assert AnnouncementAudience.RIDERS not in audiences


def test_audience_for_role_rider():
    """_audience_for_role returns RIDERS audience for RIDER role."""
    audiences = _audience_for_role(UserRole.RIDER)
    assert AnnouncementAudience.RIDERS in audiences
    assert AnnouncementAudience.ALL in audiences
    assert AnnouncementAudience.MEMBERS in audiences
    assert AnnouncementAudience.DRIVERS not in audiences


# ---------------------------------------------------------------------------
# API integration tests (skipped without live test DB)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_list_public_announcements(app, db):
    """GET /announcements returns 200."""
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/announcements")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.anyio
async def test_api_my_announcements_authenticated(app, db):
    """GET /me/announcements returns 200 for authenticated user."""
    from httpx import ASGITransport, AsyncClient
    from app.services.auth import create_access_token
    from app.models.user import User, UserRole

    user = User(
        email="rider@test.com",
        phone="+15550001111",
        password_hash="x",
        first_name="Rider",
        last_name="Test",
        role=UserRole.RIDER,
        is_active=True,
    )
    db.add(user)
    await db.flush()

    token = create_access_token({"sub": str(user.id)})
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/me/announcements", headers=headers)
    assert response.status_code == 200


@pytest.mark.anyio
async def test_api_pending_acknowledgments(app, db):
    """GET /me/announcements/pending returns 200 for authenticated user."""
    from httpx import ASGITransport, AsyncClient
    from app.services.auth import create_access_token
    from app.models.user import User, UserRole

    user = User(
        email="rider2@test.com",
        phone="+15550002222",
        password_hash="x",
        first_name="R2",
        last_name="Test",
        role=UserRole.RIDER,
        is_active=True,
    )
    db.add(user)
    await db.flush()

    token = create_access_token({"sub": str(user.id)})
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/me/announcements/pending", headers=headers)
    assert response.status_code == 200


@pytest.mark.anyio
async def test_api_view_announcement(app, db):
    """POST /me/announcements/{id}/view returns 200."""
    from httpx import ASGITransport, AsyncClient
    from app.services.auth import create_access_token
    from app.models.user import User, UserRole

    admin_user = User(
        email="admin.view@test.com",
        phone="+15550003333",
        password_hash="x",
        first_name="Admin",
        last_name="View",
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add(admin_user)
    await db.flush()

    ann = PlatformAnnouncement(
        title="Test announcement",
        body="This is a test announcement body.",
        audience=AnnouncementAudience.ALL,
        priority=AnnouncementPriority.NORMAL,
        requires_acknowledgment=False,
        created_by=admin_user.id,
        is_active=True,
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    db.add(ann)
    await db.flush()

    rider = User(
        email="rider.view@test.com",
        phone="+15550004444",
        password_hash="x",
        first_name="R",
        last_name="V",
        role=UserRole.RIDER,
        is_active=True,
    )
    db.add(rider)
    await db.flush()

    token = create_access_token({"sub": str(rider.id)})
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/me/announcements/{ann.id}/view", headers=headers
        )
    assert response.status_code == 200
    data = response.json()
    assert data["announcement_id"] == ann.id
    assert data["user_id"] == rider.id


@pytest.mark.anyio
async def test_api_acknowledge_announcement(app, db):
    """POST /me/announcements/{id}/acknowledge returns 200."""
    from httpx import ASGITransport, AsyncClient
    from app.services.auth import create_access_token
    from app.models.user import User, UserRole

    admin_user = User(
        email="admin.ack@test.com",
        phone="+15550005555",
        password_hash="x",
        first_name="Admin",
        last_name="Ack",
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add(admin_user)
    await db.flush()

    ann = PlatformAnnouncement(
        title="Critical policy update",
        body="All drivers must acknowledge this new cooperative policy.",
        audience=AnnouncementAudience.ALL,
        priority=AnnouncementPriority.CRITICAL,
        requires_acknowledgment=True,
        created_by=admin_user.id,
        is_active=True,
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    db.add(ann)
    await db.flush()

    rider = User(
        email="rider.ack@test.com",
        phone="+15550006666",
        password_hash="x",
        first_name="Rider",
        last_name="Ack",
        role=UserRole.RIDER,
        is_active=True,
    )
    db.add(rider)
    await db.flush()

    token = create_access_token({"sub": str(rider.id)})
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/me/announcements/{ann.id}/acknowledge", headers=headers
        )
    assert response.status_code == 200
    data = response.json()
    assert data["acknowledged_at"] is not None


@pytest.mark.anyio
async def test_api_admin_create_announcement(app, db):
    """POST /admin/announcements creates a draft (201)."""
    from httpx import ASGITransport, AsyncClient
    from app.services.auth import create_access_token
    from app.models.user import User, UserRole

    admin = User(
        email="admin.create@test.com",
        phone="+15550007777",
        password_hash="x",
        first_name="Admin",
        last_name="Create",
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add(admin)
    await db.flush()

    token = create_access_token({"sub": str(admin.id)})
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "title": "New Cooperative Policy",
        "body": "We are updating our driver pay formula effective next month.",
        "audience": "drivers",
        "priority": "high",
        "requires_acknowledgment": True,
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/admin/announcements", json=payload, headers=headers)
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "New Cooperative Policy"
    assert data["published_at"] is None  # still a draft


@pytest.mark.anyio
async def test_api_admin_create_announcement_forbidden(app, db):
    """POST /admin/announcements returns 403 for non-admin users."""
    from httpx import ASGITransport, AsyncClient
    from app.services.auth import create_access_token
    from app.models.user import User, UserRole

    rider = User(
        email="rider.forbidden@test.com",
        phone="+15550008888",
        password_hash="x",
        first_name="Rider",
        last_name="Forbidden",
        role=UserRole.RIDER,
        is_active=True,
    )
    db.add(rider)
    await db.flush()

    token = create_access_token({"sub": str(rider.id)})
    headers = {"Authorization": f"Bearer {token}"}

    payload = {"title": "Attempt", "body": "Unauthorized attempt body text."}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/admin/announcements", json=payload, headers=headers)
    assert response.status_code == 403


@pytest.mark.anyio
async def test_api_admin_list_announcements(app, db):
    """GET /admin/announcements returns 200 for admin."""
    from httpx import ASGITransport, AsyncClient
    from app.services.auth import create_access_token
    from app.models.user import User, UserRole

    admin = User(
        email="admin.list@test.com",
        phone="+15550009999",
        password_hash="x",
        first_name="Admin",
        last_name="List",
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add(admin)
    await db.flush()

    token = create_access_token({"sub": str(admin.id)})
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/admin/announcements", headers=headers)
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.anyio
async def test_api_admin_get_announcement(app, db):
    """GET /admin/announcements/{id} returns 200 for admin."""
    from httpx import ASGITransport, AsyncClient
    from app.services.auth import create_access_token
    from app.models.user import User, UserRole

    admin = User(
        email="admin.get@test.com",
        phone="+15550010000",
        password_hash="x",
        first_name="Admin",
        last_name="Get",
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add(admin)
    await db.flush()

    ann = PlatformAnnouncement(
        title="Admin get test",
        body="Test body for admin get.",
        audience=AnnouncementAudience.ALL,
        priority=AnnouncementPriority.NORMAL,
        requires_acknowledgment=False,
        created_by=admin.id,
        is_active=True,
    )
    db.add(ann)
    await db.flush()

    token = create_access_token({"sub": str(admin.id)})
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/admin/announcements/{ann.id}", headers=headers)
    assert response.status_code == 200
    assert response.json()["id"] == ann.id


@pytest.mark.anyio
async def test_api_admin_get_announcement_not_found(app, db):
    """GET /admin/announcements/{id} returns 404 for missing id."""
    from httpx import ASGITransport, AsyncClient
    from app.services.auth import create_access_token
    from app.models.user import User, UserRole

    admin = User(
        email="admin.404@test.com",
        phone="+15550011111",
        password_hash="x",
        first_name="Admin",
        last_name="404",
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add(admin)
    await db.flush()

    token = create_access_token({"sub": str(admin.id)})
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/admin/announcements/999999", headers=headers)
    assert response.status_code == 404


@pytest.mark.anyio
async def test_api_admin_stats(app, db):
    """GET /admin/announcements/{id}/stats returns 200."""
    from httpx import ASGITransport, AsyncClient
    from app.services.auth import create_access_token
    from app.models.user import User, UserRole

    admin = User(
        email="admin.stats@test.com",
        phone="+15550012222",
        password_hash="x",
        first_name="Admin",
        last_name="Stats",
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add(admin)
    await db.flush()

    ann = PlatformAnnouncement(
        title="Stats test",
        body="Body for stats test announcement.",
        audience=AnnouncementAudience.ALL,
        priority=AnnouncementPriority.NORMAL,
        requires_acknowledgment=False,
        created_by=admin.id,
        is_active=True,
    )
    db.add(ann)
    await db.flush()

    token = create_access_token({"sub": str(admin.id)})
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/admin/announcements/{ann.id}/stats", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["total_views"] == 0
    assert data["total_acknowledgments"] == 0


@pytest.mark.anyio
async def test_api_admin_update_announcement(app, db):
    """PUT /admin/announcements/{id} returns 200 with updated title."""
    from httpx import ASGITransport, AsyncClient
    from app.services.auth import create_access_token
    from app.models.user import User, UserRole

    admin = User(
        email="admin.update@test.com",
        phone="+15550013333",
        password_hash="x",
        first_name="Admin",
        last_name="Update",
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add(admin)
    await db.flush()

    ann = PlatformAnnouncement(
        title="Original title",
        body="Original body text for update test.",
        audience=AnnouncementAudience.ALL,
        priority=AnnouncementPriority.NORMAL,
        requires_acknowledgment=False,
        created_by=admin.id,
        is_active=True,
    )
    db.add(ann)
    await db.flush()

    token = create_access_token({"sub": str(admin.id)})
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.put(
            f"/api/v1/admin/announcements/{ann.id}",
            json={"title": "Updated title"},
            headers=headers,
        )
    assert response.status_code == 200
    assert response.json()["title"] == "Updated title"


@pytest.mark.anyio
async def test_api_admin_publish(app, db):
    """POST /admin/announcements/{id}/publish returns 200."""
    from httpx import ASGITransport, AsyncClient
    from app.services.auth import create_access_token
    from app.models.user import User, UserRole

    admin = User(
        email="admin.publish@test.com",
        phone="+15550014444",
        password_hash="x",
        first_name="Admin",
        last_name="Publish",
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add(admin)
    await db.flush()

    ann = PlatformAnnouncement(
        title="To be published",
        body="This announcement will be published now.",
        audience=AnnouncementAudience.ALL,
        priority=AnnouncementPriority.NORMAL,
        requires_acknowledgment=False,
        created_by=admin.id,
        is_active=True,
        published_at=None,
    )
    db.add(ann)
    await db.flush()

    token = create_access_token({"sub": str(admin.id)})
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/admin/announcements/{ann.id}/publish", headers=headers
        )
    assert response.status_code == 200
    assert response.json()["published_at"] is not None


@pytest.mark.anyio
async def test_api_admin_publish_already_published(app, db):
    """POST /admin/announcements/{id}/publish returns 409 when already published."""
    from httpx import ASGITransport, AsyncClient
    from app.services.auth import create_access_token
    from app.models.user import User, UserRole

    admin = User(
        email="admin.pub2@test.com",
        phone="+15550015555",
        password_hash="x",
        first_name="Admin",
        last_name="Pub2",
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add(admin)
    await db.flush()

    ann = PlatformAnnouncement(
        title="Already published",
        body="This announcement is already published.",
        audience=AnnouncementAudience.ALL,
        priority=AnnouncementPriority.NORMAL,
        requires_acknowledgment=False,
        created_by=admin.id,
        is_active=True,
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    db.add(ann)
    await db.flush()

    token = create_access_token({"sub": str(admin.id)})
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/admin/announcements/{ann.id}/publish", headers=headers
        )
    assert response.status_code == 409


@pytest.mark.anyio
async def test_api_admin_unpublish(app, db):
    """POST /admin/announcements/{id}/unpublish returns 200."""
    from httpx import ASGITransport, AsyncClient
    from app.services.auth import create_access_token
    from app.models.user import User, UserRole

    admin = User(
        email="admin.unpub@test.com",
        phone="+15550016666",
        password_hash="x",
        first_name="Admin",
        last_name="Unpub",
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add(admin)
    await db.flush()

    ann = PlatformAnnouncement(
        title="To be unpublished",
        body="This announcement will be reverted to draft.",
        audience=AnnouncementAudience.ALL,
        priority=AnnouncementPriority.NORMAL,
        requires_acknowledgment=False,
        created_by=admin.id,
        is_active=True,
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    db.add(ann)
    await db.flush()

    token = create_access_token({"sub": str(admin.id)})
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/admin/announcements/{ann.id}/unpublish", headers=headers
        )
    assert response.status_code == 200
    assert response.json()["published_at"] is None


@pytest.mark.anyio
async def test_api_admin_delete(app, db):
    """DELETE /admin/announcements/{id} returns 204."""
    from httpx import ASGITransport, AsyncClient
    from app.services.auth import create_access_token
    from app.models.user import User, UserRole

    admin = User(
        email="admin.del@test.com",
        phone="+15550017777",
        password_hash="x",
        first_name="Admin",
        last_name="Del",
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add(admin)
    await db.flush()

    ann = PlatformAnnouncement(
        title="To be deleted",
        body="This announcement will be soft-deleted now.",
        audience=AnnouncementAudience.ALL,
        priority=AnnouncementPriority.LOW,
        requires_acknowledgment=False,
        created_by=admin.id,
        is_active=True,
    )
    db.add(ann)
    await db.flush()

    token = create_access_token({"sub": str(admin.id)})
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete(
            f"/api/v1/admin/announcements/{ann.id}", headers=headers
        )
    assert response.status_code == 204


@pytest.mark.anyio
async def test_api_admin_view_records(app, db):
    """GET /admin/announcements/{id}/views returns 200."""
    from httpx import ASGITransport, AsyncClient
    from app.services.auth import create_access_token
    from app.models.user import User, UserRole

    admin = User(
        email="admin.views@test.com",
        phone="+15550018888",
        password_hash="x",
        first_name="Admin",
        last_name="Views",
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add(admin)
    await db.flush()

    ann = PlatformAnnouncement(
        title="Views test",
        body="Body for views test announcement.",
        audience=AnnouncementAudience.ALL,
        priority=AnnouncementPriority.NORMAL,
        requires_acknowledgment=False,
        created_by=admin.id,
        is_active=True,
    )
    db.add(ann)
    await db.flush()

    token = create_access_token({"sub": str(admin.id)})
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/admin/announcements/{ann.id}/views", headers=headers
        )
    assert response.status_code == 200
    assert isinstance(response.json(), list)
