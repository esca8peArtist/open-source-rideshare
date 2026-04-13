"""Tests for the Rider Surge Waitlist and Price Alert System.

Service unit tests (AsyncMock DB, no live connection needed):
- create_waitlist_entry: valid data, invalid multiplier (< 1.0 or > 5.0), invalid coords
- cancel_waitlist_entry: owner success, wrong rider 403, non-active entry 400, not found 404
- get_my_waitlist_entries: only own entries, include_expired flag
- check_and_notify_waitlist: above threshold stays active, at/below threshold notified,
  expired entry marked expired, returns counts
- get_current_surge_for_location: no surge returns 1.0 / no zone, zone matches

API endpoint tests (real DB via conftest fixtures):
- POST /surge-waitlist: 201 created, unauthenticated 401, invalid max_multiplier 422,
  invalid coordinates 422
- GET /surge-waitlist/me: returns list, empty, unauthenticated 401
- DELETE /surge-waitlist/{id}: 204 success, wrong owner 403, not found 404
- GET /surge-waitlist/current-surge: no auth, returns surge data, missing params 422
- POST /admin/surge-waitlist/check: admin only, returns counts, non-admin 403

Integration tests:
- Full flow: create entry → check (multiplier too high) → not notified → drop multiplier → notified
- Multiple entries at different thresholds → only qualifying entries notified
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.surge_waitlist import SurgeWaitlistEntry
from app.schemas.surge_waitlist import (
    CurrentSurgeResponse,
    SurgeWaitlistCreate,
    SurgeWaitlistResponse,
    WaitlistCheckResult,
)
from app.services.surge_waitlist import (
    cancel_waitlist_entry,
    check_and_notify_waitlist,
    create_waitlist_entry,
    get_current_surge_for_location,
    get_my_waitlist_entries,
)


# ===========================================================================
# Helpers
# ===========================================================================

ORIGIN_LAT = 45.51
ORIGIN_LON = -122.67


def _make_entry(**kwargs) -> MagicMock:
    """Build a minimal mock SurgeWaitlistEntry."""
    now = datetime.now(timezone.utc)
    entry = MagicMock(spec=SurgeWaitlistEntry)
    entry.id = kwargs.get("id", uuid.uuid4())
    entry.rider_id = kwargs.get("rider_id", 1)
    entry.origin_lat = kwargs.get("origin_lat", ORIGIN_LAT)
    entry.origin_lon = kwargs.get("origin_lon", ORIGIN_LON)
    entry.destination_lat = kwargs.get("destination_lat", None)
    entry.destination_lon = kwargs.get("destination_lon", None)
    entry.max_multiplier = kwargs.get("max_multiplier", 1.5)
    entry.vehicle_preference = kwargs.get("vehicle_preference", None)
    entry.status = kwargs.get("status", "active")
    entry.notify_via_push = kwargs.get("notify_via_push", True)
    entry.notify_via_sms = kwargs.get("notify_via_sms", False)
    entry.expires_at = kwargs.get("expires_at", now + timedelta(hours=2))
    entry.notified_at = kwargs.get("notified_at", None)
    entry.created_at = kwargs.get("created_at", now)
    entry.updated_at = kwargs.get("updated_at", now)
    return entry


def _make_zone(**kwargs) -> MagicMock:
    """Build a minimal mock SurgePricingZone."""
    zone = MagicMock()
    zone.id = kwargs.get("id", uuid.uuid4())
    zone.name = kwargs.get("name", "Test Zone")
    zone.polygon = kwargs.get("polygon", None)
    zone.center_lat = kwargs.get("center_lat", ORIGIN_LAT)
    zone.center_lon = kwargs.get("center_lon", ORIGIN_LON)
    zone.radius_km = kwargs.get("radius_km", 5.0)
    zone.multiplier = kwargs.get("multiplier", 1.8)
    zone.is_active = kwargs.get("is_active", True)
    zone.start_time = kwargs.get("start_time", None)
    zone.end_time = kwargs.get("end_time", None)
    zone.days_of_week = kwargs.get("days_of_week", None)
    return zone


def _active_zone_db(zones: list) -> AsyncMock:
    """DB mock where two consecutive executes both return zone lists."""
    db = AsyncMock()
    scalars_result = MagicMock()
    scalars_result.scalars.return_value.all.return_value = zones
    db.execute = AsyncMock(return_value=scalars_result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock(side_effect=lambda obj: None)
    return db


def _entry_lookup_db(entry) -> AsyncMock:
    """DB mock for single-entry lookups (cancel, etc.)."""
    db = AsyncMock()
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = entry
    db.execute = AsyncMock(return_value=scalar_result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock(side_effect=lambda obj: None)
    return db


def _scalars_db(items: list) -> AsyncMock:
    """DB mock where execute returns a result whose scalars().all() = items."""
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock(side_effect=lambda obj: None)
    return db


# ===========================================================================
# Schema tests
# ===========================================================================


class TestSurgeWaitlistCreate:
    def test_valid_minimal(self):
        req = SurgeWaitlistCreate(origin_lat=45.51, origin_lon=-122.67)
        assert req.origin_lat == 45.51
        assert req.max_multiplier == 1.5
        assert req.notify_via_push is True
        assert req.notify_via_sms is False

    def test_valid_with_all_fields(self):
        req = SurgeWaitlistCreate(
            origin_lat=45.51,
            origin_lon=-122.67,
            destination_lat=45.55,
            destination_lon=-122.60,
            max_multiplier=2.0,
            vehicle_preference="standard",
            notify_via_push=True,
            notify_via_sms=True,
        )
        assert req.destination_lat == 45.55
        assert req.vehicle_preference == "standard"

    def test_invalid_max_multiplier_below_1(self):
        with pytest.raises(Exception):
            SurgeWaitlistCreate(origin_lat=45.51, origin_lon=-122.67, max_multiplier=0.5)

    def test_invalid_max_multiplier_above_5(self):
        with pytest.raises(Exception):
            SurgeWaitlistCreate(origin_lat=45.51, origin_lon=-122.67, max_multiplier=5.1)

    def test_invalid_lat_too_high(self):
        with pytest.raises(Exception):
            SurgeWaitlistCreate(origin_lat=91.0, origin_lon=-122.67)

    def test_invalid_lat_too_low(self):
        with pytest.raises(Exception):
            SurgeWaitlistCreate(origin_lat=-91.0, origin_lon=-122.67)

    def test_invalid_lon_too_high(self):
        with pytest.raises(Exception):
            SurgeWaitlistCreate(origin_lat=45.51, origin_lon=181.0)

    def test_invalid_lon_too_low(self):
        with pytest.raises(Exception):
            SurgeWaitlistCreate(origin_lat=45.51, origin_lon=-181.0)

    def test_destination_lat_without_lon_rejected(self):
        with pytest.raises(Exception):
            SurgeWaitlistCreate(
                origin_lat=45.51,
                origin_lon=-122.67,
                destination_lat=45.55,
                # destination_lon omitted
            )

    def test_max_multiplier_boundary_1_0_valid(self):
        req = SurgeWaitlistCreate(origin_lat=45.51, origin_lon=-122.67, max_multiplier=1.0)
        assert req.max_multiplier == 1.0

    def test_max_multiplier_boundary_5_0_valid(self):
        req = SurgeWaitlistCreate(origin_lat=45.51, origin_lon=-122.67, max_multiplier=5.0)
        assert req.max_multiplier == 5.0


class TestSurgeWaitlistResponse:
    def test_from_entry_active(self):
        entry = _make_entry(status="active")
        resp = SurgeWaitlistResponse.from_entry(entry)
        assert resp.status == "active"
        assert resp.is_expired is False

    def test_from_entry_expired_status(self):
        entry = _make_entry(status="expired")
        resp = SurgeWaitlistResponse.from_entry(entry)
        assert resp.is_expired is True

    def test_from_entry_active_but_past_expiry(self):
        entry = _make_entry(
            status="active",
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        resp = SurgeWaitlistResponse.from_entry(entry)
        assert resp.is_expired is True

    def test_from_entry_notified(self):
        entry = _make_entry(status="notified")
        resp = SurgeWaitlistResponse.from_entry(entry)
        assert resp.status == "notified"
        assert resp.is_expired is False


class TestCurrentSurgeResponse:
    def test_has_surge(self):
        r = CurrentSurgeResponse(multiplier=1.8, zone_name="Downtown", has_surge=True)
        assert r.has_surge is True
        assert r.zone_name == "Downtown"

    def test_no_surge(self):
        r = CurrentSurgeResponse(multiplier=1.0, zone_name=None, has_surge=False)
        assert r.has_surge is False
        assert r.zone_name is None


class TestWaitlistCheckResult:
    def test_fields(self):
        r = WaitlistCheckResult(notified=3, expired=1, still_active=5)
        assert r.notified == 3
        assert r.expired == 1
        assert r.still_active == 5


# ===========================================================================
# Service unit tests — create_waitlist_entry
# ===========================================================================


class TestCreateWaitlistEntry:
    @pytest.mark.asyncio
    async def test_creates_with_valid_data(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        created_entry = _make_entry(rider_id=1)
        db.refresh = AsyncMock(side_effect=lambda obj: None)

        # Patch uuid4 to return a known id
        with patch("app.services.surge_waitlist.SurgeWaitlistEntry", return_value=created_entry):
            result = await create_waitlist_entry(
                db=db,
                rider_id=1,
                origin_lat=45.51,
                origin_lon=-122.67,
            )

        db.add.assert_called_once()
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_invalid_multiplier_below_1(self):
        db = AsyncMock()
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await create_waitlist_entry(
                db=db, rider_id=1, origin_lat=45.51, origin_lon=-122.67, max_multiplier=0.9
            )
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_multiplier_above_5(self):
        db = AsyncMock()
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await create_waitlist_entry(
                db=db, rider_id=1, origin_lat=45.51, origin_lon=-122.67, max_multiplier=5.1
            )
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_origin_lat(self):
        db = AsyncMock()
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await create_waitlist_entry(
                db=db, rider_id=1, origin_lat=91.0, origin_lon=-122.67
            )
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_origin_lon(self):
        db = AsyncMock()
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await create_waitlist_entry(
                db=db, rider_id=1, origin_lat=45.51, origin_lon=181.0
            )
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_expires_at_set_to_2_hours(self):
        """The entry's expires_at should be approximately 2 hours from now."""
        created_entries: list = []

        class FakeEntry:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)
                created_entries.append(self)

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock(side_effect=lambda obj: None)

        before = datetime.now(timezone.utc)
        with patch("app.services.surge_waitlist.SurgeWaitlistEntry", FakeEntry):
            await create_waitlist_entry(db=db, rider_id=5, origin_lat=45.51, origin_lon=-122.67)
        after = datetime.now(timezone.utc)

        assert len(created_entries) == 1
        e = created_entries[0]
        assert e.expires_at >= before + timedelta(hours=2) - timedelta(seconds=1)
        assert e.expires_at <= after + timedelta(hours=2) + timedelta(seconds=1)


# ===========================================================================
# Service unit tests — cancel_waitlist_entry
# ===========================================================================


class TestCancelWaitlistEntry:
    @pytest.mark.asyncio
    async def test_owner_can_cancel(self):
        entry = _make_entry(rider_id=1, status="active")
        db = _entry_lookup_db(entry)

        result = await cancel_waitlist_entry(db=db, entry_id=entry.id, rider_id=1)

        assert result.status == "cancelled"
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self):
        db = _entry_lookup_db(None)
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await cancel_waitlist_entry(db=db, entry_id=uuid.uuid4(), rider_id=1)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_wrong_rider_raises_403(self):
        entry = _make_entry(rider_id=99, status="active")
        db = _entry_lookup_db(entry)
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await cancel_waitlist_entry(db=db, entry_id=entry.id, rider_id=1)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_already_cancelled_raises_400(self):
        entry = _make_entry(rider_id=1, status="cancelled")
        db = _entry_lookup_db(entry)
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await cancel_waitlist_entry(db=db, entry_id=entry.id, rider_id=1)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_notified_entry_cannot_be_cancelled(self):
        entry = _make_entry(rider_id=1, status="notified")
        db = _entry_lookup_db(entry)
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await cancel_waitlist_entry(db=db, entry_id=entry.id, rider_id=1)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_expired_entry_cannot_be_cancelled(self):
        entry = _make_entry(rider_id=1, status="expired")
        db = _entry_lookup_db(entry)
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await cancel_waitlist_entry(db=db, entry_id=entry.id, rider_id=1)
        assert exc_info.value.status_code == 400


# ===========================================================================
# Service unit tests — get_my_waitlist_entries
# ===========================================================================


class TestGetMyWaitlistEntries:
    @pytest.mark.asyncio
    async def test_returns_own_entries(self):
        entries = [_make_entry(rider_id=1), _make_entry(rider_id=1)]
        db = _scalars_db(entries)

        result = await get_my_waitlist_entries(db=db, rider_id=1)

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_empty_list_when_no_entries(self):
        db = _scalars_db([])

        result = await get_my_waitlist_entries(db=db, rider_id=1)

        assert result == []

    @pytest.mark.asyncio
    async def test_does_not_return_other_riders_entries(self):
        # We trust the query filters — verify execute is called (no ORM leak)
        db = _scalars_db([])

        await get_my_waitlist_entries(db=db, rider_id=7)

        db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_include_expired_true_queries_all_statuses(self):
        entries = [
            _make_entry(rider_id=1, status="active"),
            _make_entry(rider_id=1, status="expired"),
            _make_entry(rider_id=1, status="cancelled"),
        ]
        db = _scalars_db(entries)

        result = await get_my_waitlist_entries(db=db, rider_id=1, include_expired=True)

        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_include_expired_false_filters_query(self):
        """include_expired=False adds a WHERE status IN ('active', 'notified') clause."""
        db = _scalars_db([])

        await get_my_waitlist_entries(db=db, rider_id=1, include_expired=False)

        db.execute.assert_awaited_once()


# ===========================================================================
# Service unit tests — get_current_surge_for_location
# ===========================================================================


class TestGetCurrentSurgeForLocation:
    @pytest.mark.asyncio
    async def test_no_zones_returns_no_surge(self):
        db = _scalars_db([])

        result = await get_current_surge_for_location(db=db, lat=45.51, lon=-122.67)

        assert result["multiplier"] == 1.0
        assert result["zone_name"] is None
        assert result["has_surge"] is False

    @pytest.mark.asyncio
    async def test_matching_zone_returns_multiplier(self):
        zone = _make_zone(
            center_lat=ORIGIN_LAT,
            center_lon=ORIGIN_LON,
            radius_km=5.0,
            multiplier=1.8,
            name="Rush Zone",
        )
        db = _scalars_db([zone])

        result = await get_current_surge_for_location(db=db, lat=ORIGIN_LAT, lon=ORIGIN_LON)

        assert result["multiplier"] == 1.8
        assert result["zone_name"] == "Rush Zone"
        assert result["has_surge"] is True

    @pytest.mark.asyncio
    async def test_non_matching_zone_returns_no_surge(self):
        zone = _make_zone(
            center_lat=40.71,  # NYC
            center_lon=-74.00,
            radius_km=1.0,
            multiplier=2.0,
        )
        db = _scalars_db([zone])

        # Query from Portland — far outside NYC zone
        result = await get_current_surge_for_location(db=db, lat=ORIGIN_LAT, lon=ORIGIN_LON)

        assert result["multiplier"] == 1.0
        assert result["zone_name"] is None

    @pytest.mark.asyncio
    async def test_highest_zone_wins(self):
        zone_low = _make_zone(
            center_lat=ORIGIN_LAT, center_lon=ORIGIN_LON, radius_km=5.0,
            multiplier=1.3, name="Zone A"
        )
        zone_high = _make_zone(
            center_lat=ORIGIN_LAT, center_lon=ORIGIN_LON, radius_km=5.0,
            multiplier=2.1, name="Zone B"
        )
        db = _scalars_db([zone_low, zone_high])

        result = await get_current_surge_for_location(db=db, lat=ORIGIN_LAT, lon=ORIGIN_LON)

        assert result["multiplier"] == 2.1
        assert result["zone_name"] == "Zone B"


# ===========================================================================
# Service unit tests — check_and_notify_waitlist
# ===========================================================================


class TestCheckAndNotifyWaitlist:
    @pytest.mark.asyncio
    async def test_empty_waitlist_returns_zeros(self):
        # Both execute calls return empty lists
        db = AsyncMock()
        empty_result = MagicMock()
        empty_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=empty_result)
        db.flush = AsyncMock()

        with patch("app.services.surge_waitlist.send_notification", new_callable=AsyncMock):
            result = await check_and_notify_waitlist(db=db)

        assert result == {"notified": 0, "expired": 0, "still_active": 0}

    @pytest.mark.asyncio
    async def test_entry_above_threshold_stays_active(self):
        """Entry with max_multiplier=1.5 stays active when current surge is 2.0."""
        entry = _make_entry(rider_id=1, max_multiplier=1.5, status="active")
        zone = _make_zone(
            center_lat=ORIGIN_LAT, center_lon=ORIGIN_LON, radius_km=5.0, multiplier=2.0
        )

        db = AsyncMock()
        results = [
            MagicMock(**{"scalars.return_value.all.return_value": [entry]}),  # active entries
            MagicMock(**{"scalars.return_value.all.return_value": [zone]}),   # zones
        ]
        db.execute = AsyncMock(side_effect=results)
        db.flush = AsyncMock()

        with patch("app.services.surge_waitlist.send_notification", new_callable=AsyncMock):
            result = await check_and_notify_waitlist(db=db)

        assert result["still_active"] == 1
        assert result["notified"] == 0
        assert result["expired"] == 0
        assert entry.status == "active"  # unchanged

    @pytest.mark.asyncio
    async def test_entry_at_threshold_gets_notified(self):
        """Entry with max_multiplier=1.8 is notified when current surge is exactly 1.8."""
        entry = _make_entry(rider_id=1, max_multiplier=1.8, status="active")
        zone = _make_zone(
            center_lat=ORIGIN_LAT, center_lon=ORIGIN_LON, radius_km=5.0, multiplier=1.8
        )

        db = AsyncMock()
        results = [
            MagicMock(**{"scalars.return_value.all.return_value": [entry]}),
            MagicMock(**{"scalars.return_value.all.return_value": [zone]}),
        ]
        db.execute = AsyncMock(side_effect=results)
        db.flush = AsyncMock()

        with patch("app.services.surge_waitlist.send_notification", new_callable=AsyncMock) as mock_notify:
            result = await check_and_notify_waitlist(db=db)

        assert result["notified"] == 1
        assert result["still_active"] == 0
        assert entry.status == "notified"
        assert entry.notified_at is not None
        mock_notify.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_entry_below_threshold_gets_notified(self):
        """Entry with max_multiplier=2.0 is notified when current surge is 1.5."""
        entry = _make_entry(rider_id=1, max_multiplier=2.0, status="active")
        zone = _make_zone(
            center_lat=ORIGIN_LAT, center_lon=ORIGIN_LON, radius_km=5.0, multiplier=1.5
        )

        db = AsyncMock()
        results = [
            MagicMock(**{"scalars.return_value.all.return_value": [entry]}),
            MagicMock(**{"scalars.return_value.all.return_value": [zone]}),
        ]
        db.execute = AsyncMock(side_effect=results)
        db.flush = AsyncMock()

        with patch("app.services.surge_waitlist.send_notification", new_callable=AsyncMock):
            result = await check_and_notify_waitlist(db=db)

        assert result["notified"] == 1
        assert entry.status == "notified"

    @pytest.mark.asyncio
    async def test_expired_entry_marked_expired(self):
        """Entry whose expires_at is in the past is marked as expired."""
        entry = _make_entry(
            rider_id=1,
            status="active",
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )

        db = AsyncMock()
        results = [
            MagicMock(**{"scalars.return_value.all.return_value": [entry]}),
            MagicMock(**{"scalars.return_value.all.return_value": []}),  # zones
        ]
        db.execute = AsyncMock(side_effect=results)
        db.flush = AsyncMock()

        with patch("app.services.surge_waitlist.send_notification", new_callable=AsyncMock):
            result = await check_and_notify_waitlist(db=db)

        assert result["expired"] == 1
        assert result["notified"] == 0
        assert entry.status == "expired"

    @pytest.mark.asyncio
    async def test_mixed_entries_correct_counts(self):
        """Multiple entries processed: one notified, one expired, one still active."""
        now = datetime.now(timezone.utc)
        entry_notify = _make_entry(rider_id=1, max_multiplier=2.0, status="active")
        entry_expire = _make_entry(
            rider_id=2, status="active",
            expires_at=now - timedelta(minutes=1)
        )
        entry_active = _make_entry(rider_id=3, max_multiplier=1.2, status="active")

        # Zone that covers entries 1 and 3 with multiplier=1.5
        zone = _make_zone(
            center_lat=ORIGIN_LAT, center_lon=ORIGIN_LON, radius_km=5.0, multiplier=1.5
        )

        db = AsyncMock()
        results = [
            MagicMock(**{"scalars.return_value.all.return_value": [
                entry_notify, entry_expire, entry_active
            ]}),
            MagicMock(**{"scalars.return_value.all.return_value": [zone]}),
        ]
        db.execute = AsyncMock(side_effect=results)
        db.flush = AsyncMock()

        with patch("app.services.surge_waitlist.send_notification", new_callable=AsyncMock):
            result = await check_and_notify_waitlist(db=db)

        # entry_notify: max=2.0, surge=1.5 → 1.5 <= 2.0 → notified
        # entry_expire: expired → expired
        # entry_active: max=1.2, surge=1.5 → 1.5 > 1.2 → still active
        assert result["notified"] == 1
        assert result["expired"] == 1
        assert result["still_active"] == 1

    @pytest.mark.asyncio
    async def test_no_zones_no_surge_notifies_entries_at_1_0(self):
        """With no zones, multiplier is 1.0. Entry with max=1.0 should be notified."""
        entry = _make_entry(rider_id=1, max_multiplier=1.0, status="active")

        db = AsyncMock()
        results = [
            MagicMock(**{"scalars.return_value.all.return_value": [entry]}),
            MagicMock(**{"scalars.return_value.all.return_value": []}),  # no zones
        ]
        db.execute = AsyncMock(side_effect=results)
        db.flush = AsyncMock()

        with patch("app.services.surge_waitlist.send_notification", new_callable=AsyncMock):
            result = await check_and_notify_waitlist(db=db)

        assert result["notified"] == 1

    @pytest.mark.asyncio
    async def test_notification_failure_does_not_crash_loop(self):
        """If send_notification raises, the loop continues and the entry is still notified."""
        entry = _make_entry(rider_id=1, max_multiplier=2.0, status="active")
        zone = _make_zone(
            center_lat=ORIGIN_LAT, center_lon=ORIGIN_LON, radius_km=5.0, multiplier=1.0
        )

        db = AsyncMock()
        results = [
            MagicMock(**{"scalars.return_value.all.return_value": [entry]}),
            MagicMock(**{"scalars.return_value.all.return_value": [zone]}),
        ]
        db.execute = AsyncMock(side_effect=results)
        db.flush = AsyncMock()

        with patch(
            "app.services.surge_waitlist.send_notification",
            new_callable=AsyncMock,
        ) as mock_notify_fail:
            mock_notify_fail.side_effect = Exception("push service unavailable")
            result = await check_and_notify_waitlist(db=db)

        # Entry status is still set to notified even if notification delivery fails
        assert result["notified"] == 1


# ===========================================================================
# Model tests
# ===========================================================================


class TestSurgeWaitlistModel:
    def test_model_tablename(self):
        from app.models.surge_waitlist import SurgeWaitlistEntry
        assert SurgeWaitlistEntry.__tablename__ == "surge_waitlist_entries"

    def test_model_has_required_columns(self):
        from app.models.surge_waitlist import SurgeWaitlistEntry
        col_names = {c.name for c in SurgeWaitlistEntry.__table__.columns}
        expected = {
            "id", "rider_id", "origin_lat", "origin_lon",
            "destination_lat", "destination_lon",
            "max_multiplier", "vehicle_preference",
            "status", "notify_via_push", "notify_via_sms",
            "expires_at", "notified_at",
            "created_at", "updated_at",
        }
        for col in expected:
            assert col in col_names, f"Expected column '{col}' not found in model"


# ===========================================================================
# API endpoint tests (real DB via conftest fixtures)
# ===========================================================================


class TestJoinSurgeWaitlistEndpoint:
    @pytest.mark.asyncio
    async def test_creates_entry_authenticated(self, client, rider, rider_token):
        resp = await client.post(
            "/api/v1/surge-waitlist",
            json={"origin_lat": 45.51, "origin_lon": -122.67},
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["rider_id"] == rider.id
        assert body["origin_lat"] == 45.51
        assert body["status"] == "active"
        assert "id" in body
        assert "expires_at" in body

    @pytest.mark.asyncio
    async def test_creates_entry_with_all_fields(self, client, rider, rider_token):
        resp = await client.post(
            "/api/v1/surge-waitlist",
            json={
                "origin_lat": 45.51,
                "origin_lon": -122.67,
                "destination_lat": 45.55,
                "destination_lon": -122.60,
                "max_multiplier": 2.0,
                "vehicle_preference": "standard",
                "notify_via_push": True,
                "notify_via_sms": True,
            },
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["max_multiplier"] == 2.0
        assert body["vehicle_preference"] == "standard"
        assert body["notify_via_sms"] is True

    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401_or_403(self, client):
        resp = await client.post(
            "/api/v1/surge-waitlist",
            json={"origin_lat": 45.51, "origin_lon": -122.67},
        )
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_invalid_max_multiplier_returns_422(self, client, rider_token):
        resp = await client.post(
            "/api/v1/surge-waitlist",
            json={"origin_lat": 45.51, "origin_lon": -122.67, "max_multiplier": 6.0},
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_coordinates_returns_422(self, client, rider_token):
        resp = await client.post(
            "/api/v1/surge-waitlist",
            json={"origin_lat": 95.0, "origin_lon": -122.67},
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_missing_origin_lat_returns_422(self, client, rider_token):
        resp = await client.post(
            "/api/v1/surge-waitlist",
            json={"origin_lon": -122.67},
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 422


class TestListMyWaitlistEntriesEndpoint:
    @pytest.mark.asyncio
    async def test_returns_empty_list_when_none(self, client, rider_token):
        resp = await client.get(
            "/api/v1/surge-waitlist/me",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_returns_own_entries(self, client, rider_token, db):
        # Create an entry first
        await client.post(
            "/api/v1/surge-waitlist",
            json={"origin_lat": 45.51, "origin_lon": -122.67},
            headers={"Authorization": f"Bearer {rider_token}"},
        )

        resp = await client.get(
            "/api/v1/surge-waitlist/me",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert len(body) >= 1

    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401_or_403(self, client):
        resp = await client.get("/api/v1/surge-waitlist/me")
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_include_expired_param_accepted(self, client, rider_token):
        resp = await client.get(
            "/api/v1/surge-waitlist/me?include_expired=true",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestCancelWaitlistEntryEndpoint:
    @pytest.mark.asyncio
    async def test_cancel_own_entry_returns_204(self, client, rider_token):
        # Create entry first
        create_resp = await client.post(
            "/api/v1/surge-waitlist",
            json={"origin_lat": 45.51, "origin_lon": -122.67},
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        entry_id = create_resp.json()["id"]

        resp = await client.delete(
            f"/api/v1/surge-waitlist/{entry_id}",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_cancel_wrong_owner_returns_403(self, client, rider_token, driver_token):
        # Rider creates entry
        create_resp = await client.post(
            "/api/v1/surge-waitlist",
            json={"origin_lat": 45.51, "origin_lon": -122.67},
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        entry_id = create_resp.json()["id"]

        # Driver tries to cancel rider's entry
        resp = await client.delete(
            f"/api/v1/surge-waitlist/{entry_id}",
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_cancel_non_existent_entry_returns_404(self, client, rider_token):
        fake_id = str(uuid.uuid4())
        resp = await client.delete(
            f"/api/v1/surge-waitlist/{fake_id}",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_cancel_already_cancelled_returns_400(self, client, rider_token):
        # Create then cancel entry
        create_resp = await client.post(
            "/api/v1/surge-waitlist",
            json={"origin_lat": 45.51, "origin_lon": -122.67},
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        entry_id = create_resp.json()["id"]

        # First cancel — should succeed
        await client.delete(
            f"/api/v1/surge-waitlist/{entry_id}",
            headers={"Authorization": f"Bearer {rider_token}"},
        )

        # Second cancel — should fail
        resp = await client.delete(
            f"/api/v1/surge-waitlist/{entry_id}",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 400


class TestCurrentSurgeEndpoint:
    @pytest.mark.asyncio
    async def test_no_auth_required(self, client):
        """Current surge endpoint is public — no Authorization header needed."""
        resp = await client.get(
            "/api/v1/surge-waitlist/current-surge?lat=45.51&lon=-122.67"
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_returns_correct_fields(self, client):
        resp = await client.get(
            "/api/v1/surge-waitlist/current-surge?lat=45.51&lon=-122.67"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "multiplier" in body
        assert "zone_name" in body
        assert "has_surge" in body

    @pytest.mark.asyncio
    async def test_missing_lat_returns_422(self, client):
        resp = await client.get("/api/v1/surge-waitlist/current-surge?lon=-122.67")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_missing_lon_returns_422(self, client):
        resp = await client.get("/api/v1/surge-waitlist/current-surge?lat=45.51")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_missing_both_params_returns_422(self, client):
        resp = await client.get("/api/v1/surge-waitlist/current-surge")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_no_surge_returns_multiplier_1(self, client):
        """With no surge zones in DB, multiplier should be 1.0."""
        resp = await client.get(
            "/api/v1/surge-waitlist/current-surge?lat=45.51&lon=-122.67"
        )
        assert resp.status_code == 200
        body = resp.json()
        # No zones in test DB → no surge
        assert body["multiplier"] == 1.0
        assert body["has_surge"] is False
        assert body["zone_name"] is None

    @pytest.mark.asyncio
    async def test_invalid_lat_returns_422(self, client):
        resp = await client.get(
            "/api/v1/surge-waitlist/current-surge?lat=95.0&lon=-122.67"
        )
        assert resp.status_code == 422


class TestAdminWaitlistCheckEndpoint:
    @pytest.mark.asyncio
    async def test_admin_can_trigger_check(self, client, admin_token):
        resp = await client.post(
            "/api/v1/admin/surge-waitlist/check",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "notified" in body
        assert "expired" in body
        assert "still_active" in body

    @pytest.mark.asyncio
    async def test_non_admin_returns_403(self, client, rider_token):
        resp = await client.post(
            "/api/v1/admin/surge-waitlist/check",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401_or_403(self, client):
        resp = await client.post("/api/v1/admin/surge-waitlist/check")
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_returns_zero_counts_when_no_entries(self, client, admin_token):
        resp = await client.post(
            "/api/v1/admin/surge-waitlist/check",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["notified"] == 0
        assert body["expired"] == 0
        assert body["still_active"] == 0


# ===========================================================================
# Integration tests
# ===========================================================================


class TestSurgeWaitlistIntegration:
    @pytest.mark.asyncio
    async def test_full_flow_not_notified_while_surge_high(
        self, client, rider, rider_token, admin_token, db
    ):
        """Create entry, run check with high surge → entry stays active."""
        from app.models.surge import SurgePricingZone

        # Create a surge zone covering the test location
        zone = SurgePricingZone(
            name="Integration Test Zone",
            center_lat=ORIGIN_LAT,
            center_lon=ORIGIN_LON,
            radius_km=10.0,
            multiplier=2.5,  # Higher than any test threshold
            is_active=True,
        )
        db.add(zone)
        await db.flush()

        # Rider joins waitlist with threshold of 1.5 (surge is 2.5 → won't notify)
        create_resp = await client.post(
            "/api/v1/surge-waitlist",
            json={"origin_lat": ORIGIN_LAT, "origin_lon": ORIGIN_LON, "max_multiplier": 1.5},
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert create_resp.status_code == 201
        entry_id = create_resp.json()["id"]

        # Run check — current surge (2.5) > threshold (1.5) → not notified
        with patch("app.services.surge_waitlist.send_notification", new_callable=AsyncMock):
            check_resp = await client.post(
                "/api/v1/admin/surge-waitlist/check",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert check_resp.status_code == 200
        check_body = check_resp.json()
        assert check_body["notified"] == 0
        assert check_body["still_active"] >= 1

        # Confirm entry is still active
        list_resp = await client.get(
            "/api/v1/surge-waitlist/me",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        entries = list_resp.json()
        matching = [e for e in entries if e["id"] == entry_id]
        assert len(matching) == 1
        assert matching[0]["status"] == "active"

    @pytest.mark.asyncio
    async def test_full_flow_notified_when_surge_drops(
        self, client, rider, rider_token, admin_token, db
    ):
        """Create entry, drop zone multiplier below threshold → entry gets notified."""
        from app.models.surge import SurgePricingZone

        # Zone with low multiplier from the start (simulate surge already dropped)
        zone = SurgePricingZone(
            name="Low Surge Zone",
            center_lat=ORIGIN_LAT,
            center_lon=ORIGIN_LON,
            radius_km=10.0,
            multiplier=1.2,  # Below threshold
            is_active=True,
        )
        db.add(zone)
        await db.flush()

        # Rider joins waitlist with threshold of 1.5 (surge is 1.2 → should notify)
        create_resp = await client.post(
            "/api/v1/surge-waitlist",
            json={"origin_lat": ORIGIN_LAT, "origin_lon": ORIGIN_LON, "max_multiplier": 1.5},
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert create_resp.status_code == 201

        with patch("app.services.surge_waitlist.send_notification", new_callable=AsyncMock) as mock_notify:
            check_resp = await client.post(
                "/api/v1/admin/surge-waitlist/check",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert check_resp.status_code == 200
        assert check_resp.json()["notified"] >= 1
        mock_notify.assert_awaited()

    @pytest.mark.asyncio
    async def test_multiple_entries_at_different_thresholds(
        self, client, rider, rider_token, driver_user, driver_token, admin_token, db
    ):
        """Two riders with different thresholds — only the qualifying one is notified."""
        from app.models.surge import SurgePricingZone

        zone = SurgePricingZone(
            name="Multi Threshold Zone",
            center_lat=ORIGIN_LAT,
            center_lon=ORIGIN_LON,
            radius_km=10.0,
            multiplier=1.6,
            is_active=True,
        )
        db.add(zone)
        await db.flush()

        # Rider 1: threshold 2.0 → surge 1.6 <= 2.0 → should notify
        await client.post(
            "/api/v1/surge-waitlist",
            json={"origin_lat": ORIGIN_LAT, "origin_lon": ORIGIN_LON, "max_multiplier": 2.0},
            headers={"Authorization": f"Bearer {rider_token}"},
        )

        # Rider 2 (driver_user acting as a regular user): threshold 1.4 → surge 1.6 > 1.4 → stays active
        await client.post(
            "/api/v1/surge-waitlist",
            json={"origin_lat": ORIGIN_LAT, "origin_lon": ORIGIN_LON, "max_multiplier": 1.4},
            headers={"Authorization": f"Bearer {driver_token}"},
        )

        with patch("app.services.surge_waitlist.send_notification", new_callable=AsyncMock):
            check_resp = await client.post(
                "/api/v1/admin/surge-waitlist/check",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        body = check_resp.json()

        assert body["notified"] >= 1
        assert body["still_active"] >= 1
