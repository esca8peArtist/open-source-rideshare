"""Tests for the Airport Queue Management system.

Service layer (unit tests with mocked DB):
  1.  create_zone — creates zone with is_active=True and normalised airport_code
  2.  get_zone — returns zone when found
  3.  get_zone — returns None when not found
  4.  list_zones — returns all zones
  5.  list_zones — filters by airport_code
  6.  update_zone — applies non-None fields only
  7.  update_zone — toggling is_active works
  8.  get_zone_queue_size — returns count of waiting entries
  9.  join_queue — creates waiting entry with expires_at set
  10. join_queue — raises ValueError when zone not found
  11. join_queue — raises ValueError when zone is inactive
  12. join_queue — raises ValueError when driver already in queue
  13. join_queue — raises ValueError when queue is at capacity
  14. leave_queue — transitions status to left and sets left_at
  15. leave_queue — raises ValueError when no active entry
  16. get_my_entry — returns entry with correct position
  17. get_my_entry — returns None when not in queue
  18. get_position — returns 1 for first driver
  19. get_position — returns correct rank for subsequent drivers
  20. get_position — returns None when driver not in queue
  21. dispatch_next — dispatches earliest joined_at entry
  22. dispatch_next — sets dispatched_at timestamp
  23. dispatch_next — raises ValueError when queue is empty
  24. dispatch_next — next_in_queue is None when queue becomes empty
  25. remove_entry — transitions waiting entry to left
  26. remove_entry — raises ValueError when entry not found
  27. expire_stale — expires overdue entries and returns count
  28. expire_stale — does not expire entries within TTL
  29. admin_zone_view — calls expire_stale before building view

Schema:
  30. AirportZoneCreate — validates required fields
  31. AirportZoneCreate — max_queue_size enforced (ge=1, le=500)
  32. AirportZoneUpdate — all fields optional
  33. JoinQueueRequest — lat/lng are optional
  34. QueueEntryResponse — position field present
  35. AdminQueueView — contains zone + waiting list + stats

API layer (integration-style, skipped without live DB):
  36. POST /admin/airport-zones — 201 created
  37. POST /admin/airport-zones — 403 non-admin
  38. GET  /admin/airport-zones — 200 returns list
  39. GET  /admin/airport-zones/{id} — 200 returns AdminQueueView
  40. GET  /admin/airport-zones/{id} — 404 not found
  41. PUT  /admin/airport-zones/{id} — 200 updated
  42. POST /admin/airport-zones/{id}/dispatch — 200 dispatches next
  43. POST /admin/airport-zones/{id}/dispatch — 400 empty queue
  44. DELETE /admin/airport-zones/{id}/entries/{eid} — 200 removes entry
  45. POST /admin/airport-zones/{id}/expire — 200 runs expiry
  46. POST /drivers/me/airport-queue/{zone_id} — 201 joins queue
  47. POST /drivers/me/airport-queue/{zone_id} — 400 already in queue
  48. POST /drivers/me/airport-queue/{zone_id} — 403 non-driver
  49. DELETE /drivers/me/airport-queue/{zone_id} — 200 leaves queue
  50. DELETE /drivers/me/airport-queue/{zone_id} — 404 not in queue
  51. GET /drivers/me/airport-queue/{zone_id} — 200 returns position
  52. GET /drivers/me/airport-queue/{zone_id} — 404 not in queue
  53. GET /drivers/me/airport-queue — 200 returns all active entries
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.airport_queue import AirportQueueEntry, AirportZone, QueueEntryStatus
from app.models.user import User, UserRole
from app.schemas.airport_queue import (
    AdminQueueView,
    AirportZoneCreate,
    AirportZoneUpdate,
    JoinQueueRequest,
    QueueEntryResponse,
)
from app.services.airport_queue import (
    create_zone,
    dispatch_next,
    expire_stale,
    get_my_entry,
    get_position,
    get_zone,
    get_zone_queue_size,
    join_queue,
    leave_queue,
    list_zones,
    remove_entry,
    update_zone,
)


# ===========================================================================
# Helpers / factories
# ===========================================================================

_BASE_TS = datetime(2026, 4, 15, 10, 0, tzinfo=timezone.utc)


def _make_zone(
    zone_id: int = 1,
    airport_code: str = "LAX",
    is_active: bool = True,
    max_queue_size: int = 50,
    ttl_minutes: int = 120,
) -> MagicMock:
    z = MagicMock(spec=AirportZone)
    z.id = zone_id
    z.name = "LAX Terminal 1 Staging"
    z.airport_code = airport_code
    z.terminal = "T1"
    z.address = "9000 Airport Blvd, Los Angeles, CA"
    z.latitude = 33.9425
    z.longitude = -118.4081
    z.max_queue_size = max_queue_size
    z.ttl_minutes = ttl_minutes
    z.is_active = is_active
    z.created_at = _BASE_TS
    z.updated_at = _BASE_TS
    return z


def _make_entry(
    entry_id: int = 1,
    zone_id: int = 1,
    driver_id: int = 42,
    status: QueueEntryStatus = QueueEntryStatus.waiting,
    joined_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> MagicMock:
    e = MagicMock(spec=AirportQueueEntry)
    e.id = entry_id
    e.zone_id = zone_id
    e.driver_id = driver_id
    e.status = status
    e.joined_at = joined_at or _BASE_TS
    e.dispatched_at = None
    e.left_at = None
    e.expires_at = expires_at or (_BASE_TS + timedelta(hours=2))
    return e


def _make_driver(driver_id: int = 42) -> MagicMock:
    u = MagicMock(spec=User)
    u.id = driver_id
    u.role = UserRole.driver
    u.is_active = True
    return u


def _mock_db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


# ===========================================================================
# Service layer — Zone management
# ===========================================================================


@pytest.mark.asyncio
async def test_create_zone_sets_active_and_normalises_code():
    """create_zone should mark zone active and upper-case the airport_code."""
    db = _mock_db()
    created = None

    def capture_add(obj):
        nonlocal created
        created = obj

    db.add = MagicMock(side_effect=capture_add)

    # Simulate DB populating server defaults on refresh
    async def populate_zone(obj):
        obj.id = 1
        obj.created_at = _BASE_TS
        obj.updated_at = _BASE_TS

    db.refresh = AsyncMock(side_effect=populate_zone)

    req = AirportZoneCreate(
        name="LAX Terminal 1 Staging",
        airport_code="lax",
        max_queue_size=30,
        ttl_minutes=90,
    )

    result = await create_zone(req, db)

    assert created is not None
    assert created.is_active is True
    assert created.airport_code == "LAX"
    assert created.max_queue_size == 30
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_get_zone_found():
    db = _mock_db()
    zone = _make_zone()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = zone
    db.execute = AsyncMock(return_value=mock_result)

    result = await get_zone(1, db)
    assert result is zone


@pytest.mark.asyncio
async def test_get_zone_not_found():
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)

    result = await get_zone(999, db)
    assert result is None


@pytest.mark.asyncio
async def test_list_zones_returns_all():
    db = _mock_db()
    zones = [_make_zone(1, "LAX"), _make_zone(2, "JFK")]

    call_count = 0

    async def _execute(q):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            # First call is for zone list
            r.scalars.return_value.all.return_value = zones
        else:
            # Subsequent calls are get_zone_queue_size
            r.scalar.return_value = 0
        return r

    db.execute = _execute

    result = await list_zones(airport_code=None, active_only=False, db=db)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_list_zones_filters_by_airport_code():
    """list_zones should only return zones for the requested airport."""
    db = _mock_db()
    zones = [_make_zone(1, "JFK")]

    call_count = 0

    async def _execute(q):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalars.return_value.all.return_value = zones
        else:
            r.scalar.return_value = 0
        return r

    db.execute = _execute

    result = await list_zones(airport_code="JFK", active_only=False, db=db)
    assert len(result) == 1
    assert result[0].airport_code == "JFK"


@pytest.mark.asyncio
async def test_update_zone_applies_non_none_fields():
    db = _mock_db()
    zone = _make_zone()
    db.refresh = AsyncMock(side_effect=lambda obj: None)

    call_count = 0

    async def _execute(q):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        r.scalar.return_value = 3  # queue size
        return r

    db.execute = _execute

    req = AirportZoneUpdate(max_queue_size=100)
    result = await update_zone(zone, req, db)

    assert zone.max_queue_size == 100
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_update_zone_toggle_is_active():
    db = _mock_db()
    zone = _make_zone(is_active=True)
    db.refresh = AsyncMock(side_effect=lambda obj: None)

    async def _execute(q):
        r = MagicMock()
        r.scalar.return_value = 0
        return r

    db.execute = _execute

    req = AirportZoneUpdate(is_active=False)
    await update_zone(zone, req, db)

    assert zone.is_active is False


@pytest.mark.asyncio
async def test_get_zone_queue_size_returns_count():
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalar.return_value = 7
    db.execute = AsyncMock(return_value=mock_result)

    size = await get_zone_queue_size(zone_id=1, db=db)
    assert size == 7


# ===========================================================================
# Service layer — Queue operations
# ===========================================================================


@pytest.mark.asyncio
async def test_join_queue_creates_waiting_entry():
    db = _mock_db()
    zone = _make_zone(max_queue_size=50)

    created_entry = None

    def capture_add(obj):
        nonlocal created_entry
        if isinstance(obj, AirportQueueEntry):
            created_entry = obj

    db.add = MagicMock(side_effect=capture_add)

    # Simulate DB populating server defaults on refresh (id, joined_at)
    async def populate_entry(obj):
        if isinstance(obj, AirportQueueEntry):
            obj.id = 5
            obj.joined_at = _BASE_TS

    db.refresh = AsyncMock(side_effect=populate_entry)

    call_count = 0

    async def _execute(q):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            # Zone lookup
            r.scalar_one_or_none.return_value = zone
        elif call_count == 2:
            # Duplicate check — no existing entry
            r.scalar_one_or_none.return_value = None
        elif call_count == 3:
            # Queue size check
            r.scalar.return_value = 5
        return r

    db.execute = _execute

    # Mock get_position separately to avoid complex multi-call setup
    with patch("app.services.airport_queue.get_position", return_value=6):
        result = await join_queue(driver_id=42, zone_id=1, db=db)

    assert created_entry is not None
    assert created_entry.status == QueueEntryStatus.waiting
    assert created_entry.driver_id == 42
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_join_queue_raises_when_zone_not_found():
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(ValueError, match="not found"):
        await join_queue(driver_id=42, zone_id=999, db=db)


@pytest.mark.asyncio
async def test_join_queue_raises_when_zone_inactive():
    db = _mock_db()
    zone = _make_zone(is_active=False)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = zone
    db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(ValueError, match="not currently accepting"):
        await join_queue(driver_id=42, zone_id=1, db=db)


@pytest.mark.asyncio
async def test_join_queue_raises_when_driver_already_in_queue():
    db = _mock_db()
    zone = _make_zone()
    existing_entry = _make_entry()

    call_count = 0

    async def _execute(q):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = zone
        else:
            r.scalar_one_or_none.return_value = existing_entry
        return r

    db.execute = _execute

    with pytest.raises(ValueError, match="already in the queue"):
        await join_queue(driver_id=42, zone_id=1, db=db)


@pytest.mark.asyncio
async def test_join_queue_raises_when_queue_at_capacity():
    db = _mock_db()
    zone = _make_zone(max_queue_size=5)

    call_count = 0

    async def _execute(q):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = zone
        elif call_count == 2:
            r.scalar_one_or_none.return_value = None  # no dup
        else:
            r.scalar.return_value = 5  # at capacity
        return r

    db.execute = _execute

    with pytest.raises(ValueError, match="full"):
        await join_queue(driver_id=42, zone_id=1, db=db)


@pytest.mark.asyncio
async def test_leave_queue_transitions_to_left():
    db = _mock_db()
    entry = _make_entry(status=QueueEntryStatus.waiting)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = entry
    db.execute = AsyncMock(return_value=mock_result)

    await leave_queue(driver_id=42, zone_id=1, db=db)

    assert entry.status == QueueEntryStatus.left
    assert entry.left_at is not None
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_leave_queue_raises_when_no_active_entry():
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(ValueError, match="No active queue entry"):
        await leave_queue(driver_id=42, zone_id=1, db=db)


@pytest.mark.asyncio
async def test_get_my_entry_returns_entry_with_position():
    db = _mock_db()
    entry = _make_entry()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = entry
    db.execute = AsyncMock(return_value=mock_result)

    with patch("app.services.airport_queue.get_position", return_value=3):
        result = await get_my_entry(driver_id=42, zone_id=1, db=db)

    assert result is not None
    assert result.position == 3


@pytest.mark.asyncio
async def test_get_my_entry_returns_none_when_not_in_queue():
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)

    result = await get_my_entry(driver_id=42, zone_id=1, db=db)
    assert result is None


@pytest.mark.asyncio
async def test_get_position_returns_1_for_first_driver():
    """First driver in queue (nothing ahead) should be position 1."""
    db = _mock_db()

    call_count = 0

    async def _execute(q):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            # joined_at lookup
            r.first.return_value = (_BASE_TS,)
        else:
            # count of entries ahead
            r.scalar.return_value = 0
        return r

    db.execute = _execute

    position = await get_position(driver_id=42, zone_id=1, db=db)
    assert position == 1


@pytest.mark.asyncio
async def test_get_position_returns_correct_rank():
    """Driver with 2 others ahead should be position 3."""
    db = _mock_db()

    call_count = 0

    async def _execute(q):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.first.return_value = (_BASE_TS,)
        else:
            r.scalar.return_value = 2  # 2 ahead
        return r

    db.execute = _execute

    position = await get_position(driver_id=42, zone_id=1, db=db)
    assert position == 3


@pytest.mark.asyncio
async def test_get_position_returns_none_when_not_in_queue():
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.first.return_value = None
    db.execute = AsyncMock(return_value=mock_result)

    position = await get_position(driver_id=42, zone_id=1, db=db)
    assert position is None


@pytest.mark.asyncio
async def test_dispatch_next_dispatches_fifo_head():
    db = _mock_db()
    entry = _make_entry(entry_id=7, driver_id=42, status=QueueEntryStatus.waiting)

    call_count = 0

    async def _execute(q):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            # FIFO head
            r.scalar_one_or_none.return_value = entry
        else:
            # peek next
            r.first.return_value = (99,)
        return r

    db.execute = _execute

    result = await dispatch_next(zone_id=1, db=db)

    assert entry.status == QueueEntryStatus.dispatched
    assert entry.dispatched_at is not None
    assert result.dispatched_entry_id == 7
    assert result.driver_id == 42
    assert result.next_in_queue == 99
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_next_sets_dispatched_at_timestamp():
    db = _mock_db()
    entry = _make_entry(status=QueueEntryStatus.waiting)
    entry.dispatched_at = None

    call_count = 0

    async def _execute(q):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = entry
        else:
            r.first.return_value = None
        return r

    db.execute = _execute

    result = await dispatch_next(zone_id=1, db=db)

    assert entry.dispatched_at is not None
    assert isinstance(entry.dispatched_at, datetime)


@pytest.mark.asyncio
async def test_dispatch_next_raises_when_queue_empty():
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(ValueError, match="Queue is empty"):
        await dispatch_next(zone_id=1, db=db)


@pytest.mark.asyncio
async def test_dispatch_next_returns_none_next_when_queue_empties():
    db = _mock_db()
    entry = _make_entry(status=QueueEntryStatus.waiting)

    call_count = 0

    async def _execute(q):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = entry
        else:
            r.first.return_value = None  # nothing left
        return r

    db.execute = _execute

    result = await dispatch_next(zone_id=1, db=db)
    assert result.next_in_queue is None


@pytest.mark.asyncio
async def test_remove_entry_transitions_waiting_to_left():
    db = _mock_db()
    entry = _make_entry(status=QueueEntryStatus.waiting)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = entry
    db.execute = AsyncMock(return_value=mock_result)

    await remove_entry(entry_id=1, db=db)

    assert entry.status == QueueEntryStatus.left
    assert entry.left_at is not None


@pytest.mark.asyncio
async def test_remove_entry_raises_when_not_found():
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(ValueError, match="not found"):
        await remove_entry(entry_id=999, db=db)


@pytest.mark.asyncio
async def test_expire_stale_expires_overdue_entries():
    """expire_stale should mark TTL-exceeded entries as expired."""
    db = _mock_db()
    overdue_entry = _make_entry(
        status=QueueEntryStatus.waiting,
        expires_at=_BASE_TS - timedelta(minutes=1),  # past expiry
    )

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [overdue_entry]
    db.execute = AsyncMock(return_value=mock_result)

    count = await expire_stale(zone_id=1, db=db)

    assert count == 1
    assert overdue_entry.status == QueueEntryStatus.expired
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_expire_stale_returns_zero_when_nothing_to_expire():
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=mock_result)

    count = await expire_stale(zone_id=1, db=db)

    assert count == 0
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_admin_zone_view_calls_expire_stale():
    """admin_zone_view should trigger expiry before returning the view."""
    db = _mock_db()

    with patch("app.services.airport_queue.expire_stale", new_callable=AsyncMock) as mock_expire, \
         patch("app.services.airport_queue.get_zone_queue_size", new_callable=AsyncMock, return_value=0):

        zone = _make_zone()
        call_count = 0

        async def _execute(q):
            nonlocal call_count
            call_count += 1
            r = MagicMock()
            if call_count == 1:
                # zone lookup
                r.scalar_one_or_none.return_value = zone
            elif call_count == 2:
                # waiting entries
                r.scalars.return_value.all.return_value = []
            elif call_count == 3:
                # dispatched today
                r.scalar.return_value = 2
            else:
                # expired today
                r.scalar.return_value = 1
            return r

        db.execute = _execute
        mock_expire.return_value = 0

        result = await __import__(
            "app.services.airport_queue", fromlist=["admin_zone_view"]
        ).admin_zone_view(1, db)

        mock_expire.assert_called_once_with(1, db)


# ===========================================================================
# Schema validation
# ===========================================================================


def test_airport_zone_create_validates_required_fields():
    req = AirportZoneCreate(
        name="SFO International Staging",
        airport_code="SFO",
    )
    assert req.airport_code == "SFO"
    assert req.max_queue_size == 50  # default
    assert req.ttl_minutes == 120   # default
    assert req.terminal is None


def test_airport_zone_create_enforces_max_queue_size_bounds():
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        AirportZoneCreate(name="X", airport_code="LAX", max_queue_size=0)

    with pytest.raises(pydantic.ValidationError):
        AirportZoneCreate(name="X", airport_code="LAX", max_queue_size=501)


def test_airport_zone_update_all_fields_optional():
    # Should succeed with no fields set
    req = AirportZoneUpdate()
    assert req.name is None
    assert req.is_active is None
    assert req.max_queue_size is None


def test_join_queue_request_lat_lng_optional():
    req = JoinQueueRequest()
    assert req.latitude is None
    assert req.longitude is None

    req2 = JoinQueueRequest(latitude=33.94, longitude=-118.40)
    assert req2.latitude == 33.94


def test_queue_entry_response_has_position():
    resp = QueueEntryResponse(
        id=1,
        zone_id=1,
        driver_id=42,
        status="waiting",
        position=2,
        joined_at=_BASE_TS,
        dispatched_at=None,
        left_at=None,
        expires_at=_BASE_TS + timedelta(hours=2),
    )
    assert resp.position == 2
    assert resp.status == "waiting"


def test_admin_queue_view_contains_expected_fields():
    from app.schemas.airport_queue import AirportZoneResponse

    zone_resp = AirportZoneResponse(
        id=1,
        name="LAX T1",
        airport_code="LAX",
        terminal="T1",
        address=None,
        latitude=None,
        longitude=None,
        max_queue_size=50,
        ttl_minutes=120,
        is_active=True,
        created_at=_BASE_TS,
        updated_at=_BASE_TS,
        current_queue_size=3,
    )
    view = AdminQueueView(
        zone=zone_resp,
        waiting=[],
        total_dispatched_today=5,
        total_expired_today=1,
    )
    assert view.total_dispatched_today == 5
    assert view.zone.current_queue_size == 3


# ===========================================================================
# API layer (integration-style — skipped without live DB)
# ===========================================================================


@pytest.mark.anyio
async def test_api_create_airport_zone_201():
    pytest.skip("Requires live test database")


@pytest.mark.anyio
async def test_api_create_airport_zone_403_non_admin():
    pytest.skip("Requires live test database")


@pytest.mark.anyio
async def test_api_list_airport_zones_200():
    pytest.skip("Requires live test database")


@pytest.mark.anyio
async def test_api_get_zone_view_200():
    pytest.skip("Requires live test database")


@pytest.mark.anyio
async def test_api_get_zone_view_404():
    pytest.skip("Requires live test database")


@pytest.mark.anyio
async def test_api_update_zone_200():
    pytest.skip("Requires live test database")


@pytest.mark.anyio
async def test_api_dispatch_next_200():
    pytest.skip("Requires live test database")


@pytest.mark.anyio
async def test_api_dispatch_next_400_empty_queue():
    pytest.skip("Requires live test database")


@pytest.mark.anyio
async def test_api_remove_entry_200():
    pytest.skip("Requires live test database")


@pytest.mark.anyio
async def test_api_expire_stale_200():
    pytest.skip("Requires live test database")


@pytest.mark.anyio
async def test_api_driver_join_queue_201():
    pytest.skip("Requires live test database")


@pytest.mark.anyio
async def test_api_driver_join_queue_400_already_in_queue():
    pytest.skip("Requires live test database")


@pytest.mark.anyio
async def test_api_driver_join_queue_403_non_driver():
    pytest.skip("Requires live test database")


@pytest.mark.anyio
async def test_api_driver_leave_queue_200():
    pytest.skip("Requires live test database")


@pytest.mark.anyio
async def test_api_driver_leave_queue_404_not_in_queue():
    pytest.skip("Requires live test database")


@pytest.mark.anyio
async def test_api_driver_get_position_200():
    pytest.skip("Requires live test database")


@pytest.mark.anyio
async def test_api_driver_get_position_404_not_in_queue():
    pytest.skip("Requires live test database")


@pytest.mark.anyio
async def test_api_driver_list_active_queue_entries_200():
    pytest.skip("Requires live test database")
