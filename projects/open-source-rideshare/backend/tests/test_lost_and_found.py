"""Tests for the lost and found system (separate lost/found model design).

Covers:
1.  Service: create_lost_report — with and without ride_id
2.  Service: create_found_report — with and without ride_id
3.  Service: create_lost_report — 404 when ride not found
4.  Service: create_lost_report — 403 when rider not a participant
5.  Service: create_found_report — 403 when driver not the driver on ride
6.  Service: get_lost_report — 404 when not found
7.  Service: get_found_report — 404 when not found
8.  Service: get_rider_lost_reports — returns only this rider's reports
9.  Service: get_driver_found_reports — returns only this driver's reports
10. Service: admin_list_lost_reports — no filter returns all
11. Service: admin_list_lost_reports — filter by status
12. Service: admin_list_found_reports — no filter returns all
13. Service: admin_list_found_reports — filter by status
14. Service: match_reports — sets both to MATCHED and links IDs
15. Service: match_reports — 404 when lost report missing
16. Service: match_reports — 404 when found report missing
17. Service: match_reports — 409 when lost report already terminal
18. Service: match_reports — 409 when found report already terminal
19. Service: match_reports — 409 when lost already MATCHED
20. Service: match_reports — 409 when found already MATCHED
21. Service: mark_returned — sets found→RETURNED_TO_OWNER, lost→RETURNED
22. Service: mark_returned — 409 when found not in MATCHED status
23. Service: mark_returned — 404 when found not found
24. Service: mark_returned — works without a linked lost report
25. Service: discard_found_item — sets found→DISCARDED
26. Service: discard_found_item — 409 when already terminal
27. Service: discard_found_item — 404 when not found
28. Service: close_lost_report — sets lost→CLOSED_NO_MATCH
29. Service: close_lost_report — 409 when already terminal
30. Service: close_lost_report — 404 when not found
31. API: POST /riders/me/lost-items — 201 on success
32. API: POST /riders/me/lost-items — 401 when unauthenticated
33. API: POST /riders/me/lost-items — 422 when description too long
34. API: POST /riders/me/lost-items — 422 when invalid category
35. API: GET  /riders/me/lost-items — returns own reports
36. API: GET  /riders/me/lost-items — 401 when unauthenticated
37. API: GET  /riders/me/lost-items/{id} — returns own report
38. API: GET  /riders/me/lost-items/{id} — 403 for another rider's report
39. API: GET  /riders/me/lost-items/{id} — 404 when not found
40. API: POST /drivers/me/found-items-v2 — 201 on success
41. API: POST /drivers/me/found-items-v2 — 403 when not a driver
42. API: GET  /drivers/me/found-items-v2 — returns own reports
43. API: GET  /drivers/me/found-items-v2 — 403 when rider tries
44. API: GET  /drivers/me/found-items-v2/{id} — returns own report
45. API: GET  /drivers/me/found-items-v2/{id} — 403 for another driver's report
46. API: GET  /admin/lost-and-found/lost-reports — 200 with list
47. API: GET  /admin/lost-and-found/lost-reports — 403 for non-admin
48. API: GET  /admin/lost-and-found/lost-reports?status=open — filtered
49. API: GET  /admin/lost-and-found/found-reports — 200 with list
50. API: GET  /admin/lost-and-found/found-reports?status=pending_match — filtered
51. API: GET  /admin/lost-and-found/lost-reports/{id} — 200 for any report
52. API: GET  /admin/lost-and-found/found-reports/{id} — 404 when missing
53. API: POST /admin/lost-and-found/match — sets both to matched
54. API: POST /admin/lost-and-found/match — 409 when already resolved
55. API: POST /admin/lost-and-found/found-reports/{id}/mark-returned — 200
56. API: POST /admin/lost-and-found/found-reports/{id}/mark-returned — 409 not matched
57. API: POST /admin/lost-and-found/found-reports/{id}/discard — 200
58. API: POST /admin/lost-and-found/found-reports/{id}/discard — 409 when terminal
59. API: POST /admin/lost-and-found/lost-reports/{id}/close — 200
60. API: POST /admin/lost-and-found/lost-reports/{id}/close — 409 when terminal
61. API: Admin pagination — limit/offset respected
62. API: Admin pagination — offset beyond results returns empty list
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.lost_and_found import (
    ContactPreference,
    ItemCategory,
    LafFoundItemReport,
    LafFoundItemStatus,
    LafLostItemReport,
    LafLostItemStatus,
)
from app.models.ride import Ride, RideStatus
from app.models.user import User, UserRole
from app.services.auth import create_access_token, hash_password
from app.services.lost_and_found import (
    LostAndFoundError,
    admin_list_found_reports,
    admin_list_lost_reports,
    close_lost_report,
    create_found_report,
    create_lost_report,
    discard_found_item,
    get_driver_found_reports,
    get_found_report,
    get_lost_report,
    get_rider_lost_reports,
    mark_returned,
    match_reports,
)

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

_TODAY = date.today()


def _make_lost(
    report_id: int = 1,
    rider_id: int = 10,
    status: LafLostItemStatus = LafLostItemStatus.OPEN,
    matched_found_report_id: int | None = None,
) -> MagicMock:
    r = MagicMock(spec=LafLostItemReport)
    r.id = report_id
    r.rider_id = rider_id
    r.ride_id = None
    r.description = "Blue headphones"
    r.category = ItemCategory.ELECTRONICS
    r.date_lost = _TODAY
    r.contact_preference = ContactPreference.APP_MESSAGE
    r.status = status
    r.matched_found_report_id = matched_found_report_id
    r.matched_found_report = None
    r.resolved_at = None
    r.created_at = datetime.now(timezone.utc)
    r.updated_at = datetime.now(timezone.utc)
    return r


def _make_found(
    report_id: int = 2,
    driver_id: int = 20,
    status: LafFoundItemStatus = LafFoundItemStatus.PENDING_MATCH,
    matched_lost_report_id: int | None = None,
) -> MagicMock:
    r = MagicMock(spec=LafFoundItemReport)
    r.id = report_id
    r.driver_id = driver_id
    r.ride_id = None
    r.description = "Blue headphones"
    r.category = ItemCategory.ELECTRONICS
    r.date_found = _TODAY
    r.storage_location = "Front seat"
    r.status = status
    r.matched_lost_report_id = matched_lost_report_id
    r.matched_lost_report_ref = None
    r.resolved_at = None
    r.created_at = datetime.now(timezone.utc)
    r.updated_at = datetime.now(timezone.utc)
    return r


def _make_ride(ride_id: int = 1, rider_id: int = 10, driver_id: int = 20) -> MagicMock:
    ride = MagicMock()
    ride.id = ride_id
    ride.rider_id = rider_id
    ride.driver_id = driver_id
    ride.status = RideStatus.COMPLETED
    return ride


def _single_db(obj) -> AsyncMock:
    """DB mock returning obj from scalar_one_or_none on execute."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = obj
    # scalars().all() for list queries
    scalars = MagicMock()
    scalars.all.return_value = [obj] if obj is not None else []
    result.scalars.return_value = scalars
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _multi_db(*objects) -> AsyncMock:
    """DB mock where successive execute calls return each object."""
    db = AsyncMock()
    results = []
    for obj in objects:
        r = MagicMock()
        r.scalar_one_or_none.return_value = obj
        scalars = MagicMock()
        scalars.all.return_value = [obj] if obj is not None else []
        r.scalars.return_value = scalars
        results.append(r)
    db.execute = AsyncMock(side_effect=results)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _scalars_db(items: list) -> AsyncMock:
    """DB mock where execute returns scalars().all() = items."""
    db = AsyncMock()
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = items
    result.scalars.return_value = scalars
    result.scalar_one_or_none.return_value = items[0] if items else None
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Service tests: create_lost_report
# ---------------------------------------------------------------------------


class TestCreateLostReport:
    @pytest.mark.asyncio
    async def test_creates_report_without_ride_id(self):
        db = _single_db(None)
        report = await create_lost_report(
            db,
            rider_id=10,
            description="Black backpack",
            category=ItemCategory.BAGS,
            date_lost=_TODAY,
            contact_preference=ContactPreference.EMAIL,
        )
        db.add.assert_called_once()
        added = db.add.call_args[0][0]
        assert isinstance(added, LafLostItemReport)
        assert added.rider_id == 10
        assert added.status == LafLostItemStatus.OPEN
        assert added.category == ItemCategory.BAGS
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_creates_report_with_valid_ride_id(self):
        ride = _make_ride(ride_id=5, rider_id=10)
        db = _single_db(ride)
        await create_lost_report(
            db,
            rider_id=10,
            description="Sunglasses",
            category=ItemCategory.OTHER,
            date_lost=_TODAY,
            contact_preference=ContactPreference.PHONE,
            ride_id=5,
        )
        added = db.add.call_args[0][0]
        assert added.ride_id == 5

    @pytest.mark.asyncio
    async def test_raises_404_when_ride_not_found(self):
        db = _single_db(None)
        with pytest.raises(LostAndFoundError) as exc_info:
            await create_lost_report(
                db,
                rider_id=10,
                description="Phone",
                category=ItemCategory.ELECTRONICS,
                date_lost=_TODAY,
                contact_preference=ContactPreference.APP_MESSAGE,
                ride_id=999,
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_raises_403_when_not_rider_on_ride(self):
        ride = _make_ride(ride_id=5, rider_id=99, driver_id=88)
        db = _single_db(ride)
        with pytest.raises(LostAndFoundError) as exc_info:
            await create_lost_report(
                db,
                rider_id=10,
                description="Keys",
                category=ItemCategory.KEYS,
                date_lost=_TODAY,
                contact_preference=ContactPreference.APP_MESSAGE,
                ride_id=5,
            )
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Service tests: create_found_report
# ---------------------------------------------------------------------------


class TestCreateFoundReport:
    @pytest.mark.asyncio
    async def test_creates_report_without_ride_id(self):
        db = _single_db(None)
        await create_found_report(
            db,
            driver_id=20,
            description="Red jacket",
            category=ItemCategory.CLOTHING,
            date_found=_TODAY,
            storage_location="Glove box",
        )
        added = db.add.call_args[0][0]
        assert isinstance(added, LafFoundItemReport)
        assert added.driver_id == 20
        assert added.status == LafFoundItemStatus.PENDING_MATCH
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_creates_report_with_valid_ride_id(self):
        ride = _make_ride(ride_id=5, driver_id=20)
        db = _single_db(ride)
        await create_found_report(
            db,
            driver_id=20,
            description="Scarf",
            category=ItemCategory.CLOTHING,
            date_found=_TODAY,
            storage_location="Back seat",
            ride_id=5,
        )
        added = db.add.call_args[0][0]
        assert added.ride_id == 5

    @pytest.mark.asyncio
    async def test_raises_403_when_not_driver_on_ride(self):
        ride = _make_ride(ride_id=5, driver_id=99)
        db = _single_db(ride)
        with pytest.raises(LostAndFoundError) as exc_info:
            await create_found_report(
                db,
                driver_id=20,
                description="Hat",
                category=ItemCategory.CLOTHING,
                date_found=_TODAY,
                storage_location="Trunk",
                ride_id=5,
            )
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_raises_404_when_ride_not_found(self):
        db = _single_db(None)
        with pytest.raises(LostAndFoundError) as exc_info:
            await create_found_report(
                db,
                driver_id=20,
                description="Hat",
                category=ItemCategory.CLOTHING,
                date_found=_TODAY,
                storage_location="Trunk",
                ride_id=999,
            )
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service tests: get_lost_report / get_found_report
# ---------------------------------------------------------------------------


class TestGetReports:
    @pytest.mark.asyncio
    async def test_get_lost_report_returns_report(self):
        report = _make_lost(report_id=1)
        db = _single_db(report)
        result = await get_lost_report(db, lost_id=1)
        assert result is report

    @pytest.mark.asyncio
    async def test_get_lost_report_raises_404(self):
        db = _single_db(None)
        with pytest.raises(LostAndFoundError) as exc_info:
            await get_lost_report(db, lost_id=999)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_found_report_returns_report(self):
        report = _make_found(report_id=2)
        db = _single_db(report)
        result = await get_found_report(db, found_id=2)
        assert result is report

    @pytest.mark.asyncio
    async def test_get_found_report_raises_404(self):
        db = _single_db(None)
        with pytest.raises(LostAndFoundError) as exc_info:
            await get_found_report(db, found_id=999)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service tests: list queries
# ---------------------------------------------------------------------------


class TestListQueries:
    @pytest.mark.asyncio
    async def test_get_rider_lost_reports_returns_own(self):
        reports = [_make_lost(report_id=1, rider_id=10), _make_lost(report_id=2, rider_id=10)]
        db = _scalars_db(reports)
        result = await get_rider_lost_reports(db, rider_id=10)
        assert result == reports

    @pytest.mark.asyncio
    async def test_get_driver_found_reports_returns_own(self):
        reports = [_make_found(report_id=1, driver_id=20)]
        db = _scalars_db(reports)
        result = await get_driver_found_reports(db, driver_id=20)
        assert result == reports

    @pytest.mark.asyncio
    async def test_admin_list_lost_returns_all(self):
        reports = [_make_lost(report_id=i) for i in range(3)]
        db = _scalars_db(reports)
        result = await admin_list_lost_reports(db)
        assert result == reports

    @pytest.mark.asyncio
    async def test_admin_list_lost_filter_by_status(self):
        open_report = _make_lost(report_id=1, status=LafLostItemStatus.OPEN)
        db = _scalars_db([open_report])
        result = await admin_list_lost_reports(db, status=LafLostItemStatus.OPEN)
        assert result == [open_report]

    @pytest.mark.asyncio
    async def test_admin_list_found_returns_all(self):
        reports = [_make_found(report_id=i) for i in range(2)]
        db = _scalars_db(reports)
        result = await admin_list_found_reports(db)
        assert result == reports

    @pytest.mark.asyncio
    async def test_admin_list_found_filter_by_status(self):
        matched = _make_found(report_id=1, status=LafFoundItemStatus.MATCHED)
        db = _scalars_db([matched])
        result = await admin_list_found_reports(db, status=LafFoundItemStatus.MATCHED)
        assert result == [matched]


# ---------------------------------------------------------------------------
# Service tests: match_reports
# ---------------------------------------------------------------------------


class TestMatchReports:
    @pytest.mark.asyncio
    async def test_match_sets_both_to_matched_and_links_ids(self):
        lost = _make_lost(report_id=1, status=LafLostItemStatus.OPEN)
        found = _make_found(report_id=2, status=LafFoundItemStatus.PENDING_MATCH)
        db = _multi_db(lost, found)

        result_lost, result_found = await match_reports(db, lost_id=1, found_id=2, admin_id=99)

        assert result_lost.status == LafLostItemStatus.MATCHED
        assert result_lost.matched_found_report_id == 2
        assert result_found.status == LafFoundItemStatus.MATCHED
        assert result_found.matched_lost_report_id == 1
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_match_raises_404_when_lost_not_found(self):
        db = _single_db(None)
        with pytest.raises(LostAndFoundError) as exc_info:
            await match_reports(db, lost_id=999, found_id=2, admin_id=99)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_match_raises_404_when_found_not_found(self):
        lost = _make_lost(report_id=1)
        db = _multi_db(lost, None)
        with pytest.raises(LostAndFoundError) as exc_info:
            await match_reports(db, lost_id=1, found_id=999, admin_id=99)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_match_raises_409_when_lost_already_terminal(self):
        lost = _make_lost(report_id=1, status=LafLostItemStatus.RETURNED)
        found = _make_found(report_id=2)
        db = _multi_db(lost, found)
        with pytest.raises(LostAndFoundError) as exc_info:
            await match_reports(db, lost_id=1, found_id=2, admin_id=99)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_match_raises_409_when_found_already_terminal(self):
        lost = _make_lost(report_id=1)
        found = _make_found(report_id=2, status=LafFoundItemStatus.DISCARDED)
        db = _multi_db(lost, found)
        with pytest.raises(LostAndFoundError) as exc_info:
            await match_reports(db, lost_id=1, found_id=2, admin_id=99)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_match_raises_409_when_lost_already_matched(self):
        lost = _make_lost(report_id=1, status=LafLostItemStatus.MATCHED)
        found = _make_found(report_id=2)
        db = _multi_db(lost, found)
        with pytest.raises(LostAndFoundError) as exc_info:
            await match_reports(db, lost_id=1, found_id=2, admin_id=99)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_match_raises_409_when_found_already_matched(self):
        lost = _make_lost(report_id=1)
        found = _make_found(report_id=2, status=LafFoundItemStatus.MATCHED)
        db = _multi_db(lost, found)
        with pytest.raises(LostAndFoundError) as exc_info:
            await match_reports(db, lost_id=1, found_id=2, admin_id=99)
        assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# Service tests: mark_returned
# ---------------------------------------------------------------------------


class TestMarkReturned:
    @pytest.mark.asyncio
    async def test_sets_found_to_returned_to_owner(self):
        found = _make_found(report_id=2, status=LafFoundItemStatus.MATCHED, matched_lost_report_id=None)
        db = _single_db(found)
        result_found, result_lost = await mark_returned(db, found_id=2, admin_id=99)
        assert result_found.status == LafFoundItemStatus.RETURNED_TO_OWNER
        assert result_found.resolved_at is not None
        assert result_lost is None

    @pytest.mark.asyncio
    async def test_also_sets_linked_lost_report_to_returned(self):
        found = _make_found(report_id=2, status=LafFoundItemStatus.MATCHED, matched_lost_report_id=1)
        lost = _make_lost(report_id=1, status=LafLostItemStatus.MATCHED)
        db = _multi_db(found, lost)
        result_found, result_lost = await mark_returned(db, found_id=2, admin_id=99)
        assert result_found.status == LafFoundItemStatus.RETURNED_TO_OWNER
        assert result_lost is not None
        assert result_lost.status == LafLostItemStatus.RETURNED

    @pytest.mark.asyncio
    async def test_raises_409_when_found_not_matched(self):
        found = _make_found(report_id=2, status=LafFoundItemStatus.PENDING_MATCH)
        db = _single_db(found)
        with pytest.raises(LostAndFoundError) as exc_info:
            await mark_returned(db, found_id=2, admin_id=99)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_raises_404_when_found_not_found(self):
        db = _single_db(None)
        with pytest.raises(LostAndFoundError) as exc_info:
            await mark_returned(db, found_id=999, admin_id=99)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service tests: discard_found_item
# ---------------------------------------------------------------------------


class TestDiscardFoundItem:
    @pytest.mark.asyncio
    async def test_sets_found_to_discarded(self):
        found = _make_found(report_id=2, status=LafFoundItemStatus.PENDING_MATCH)
        db = _single_db(found)
        result = await discard_found_item(db, found_id=2, admin_id=99)
        assert result.status == LafFoundItemStatus.DISCARDED
        assert result.resolved_at is not None

    @pytest.mark.asyncio
    async def test_raises_409_when_already_terminal(self):
        found = _make_found(report_id=2, status=LafFoundItemStatus.RETURNED_TO_OWNER)
        db = _single_db(found)
        with pytest.raises(LostAndFoundError) as exc_info:
            await discard_found_item(db, found_id=2, admin_id=99)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_raises_404_when_not_found(self):
        db = _single_db(None)
        with pytest.raises(LostAndFoundError) as exc_info:
            await discard_found_item(db, found_id=999, admin_id=99)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service tests: close_lost_report
# ---------------------------------------------------------------------------


class TestCloseLostReport:
    @pytest.mark.asyncio
    async def test_sets_lost_to_closed_no_match(self):
        lost = _make_lost(report_id=1, status=LafLostItemStatus.OPEN)
        db = _single_db(lost)
        result = await close_lost_report(db, lost_id=1, admin_id=99)
        assert result.status == LafLostItemStatus.CLOSED_NO_MATCH
        assert result.resolved_at is not None

    @pytest.mark.asyncio
    async def test_raises_409_when_already_terminal(self):
        lost = _make_lost(report_id=1, status=LafLostItemStatus.CLOSED_NO_MATCH)
        db = _single_db(lost)
        with pytest.raises(LostAndFoundError) as exc_info:
            await close_lost_report(db, lost_id=1, admin_id=99)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_raises_409_when_already_returned(self):
        lost = _make_lost(report_id=1, status=LafLostItemStatus.RETURNED)
        db = _single_db(lost)
        with pytest.raises(LostAndFoundError) as exc_info:
            await close_lost_report(db, lost_id=1, admin_id=99)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_raises_404_when_not_found(self):
        db = _single_db(None)
        with pytest.raises(LostAndFoundError) as exc_info:
            await close_lost_report(db, lost_id=999, admin_id=99)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# API endpoint tests — helpers
# ---------------------------------------------------------------------------


def _insert_ride(db, rider_id: int, driver_id: int) -> Ride:
    ride = Ride(
        rider_id=rider_id,
        driver_id=driver_id,
        status=RideStatus.COMPLETED,
        pickup_location="SRID=4326;POINT(-73.9857 40.7484)",
        dropoff_location="SRID=4326;POINT(-73.9857 40.7484)",
        pickup_address="123 Start St",
        dropoff_address="456 End Ave",
        estimated_fare=12.0,
        actual_fare=12.0,
    )
    db.add(ride)
    return ride


def _insert_lost(db, rider_id: int, status: LafLostItemStatus = LafLostItemStatus.OPEN) -> LafLostItemReport:
    r = LafLostItemReport(
        rider_id=rider_id,
        description="Black backpack",
        category=ItemCategory.BAGS,
        date_lost=_TODAY,
        contact_preference=ContactPreference.APP_MESSAGE,
        status=status,
    )
    db.add(r)
    return r


def _insert_found(
    db, driver_id: int, status: LafFoundItemStatus = LafFoundItemStatus.PENDING_MATCH
) -> LafFoundItemReport:
    r = LafFoundItemReport(
        driver_id=driver_id,
        description="Brown wallet",
        category=ItemCategory.OTHER,
        date_found=_TODAY,
        storage_location="Glove box",
        status=status,
    )
    db.add(r)
    return r


# ---------------------------------------------------------------------------
# API endpoint tests — rider endpoints
# ---------------------------------------------------------------------------


class TestRiderLostItemAPI:
    @pytest.mark.asyncio
    async def test_create_lost_item_201(self, client, rider, rider_token):
        resp = await client.post(
            "/api/v1/riders/me/lost-items",
            json={
                "description": "Blue wireless headphones",
                "category": "electronics",
                "date_lost": str(_TODAY),
                "contact_preference": "app_message",
            },
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["description"] == "Blue wireless headphones"
        assert body["status"] == "open"
        assert body["rider_id"] == rider.id

    @pytest.mark.asyncio
    async def test_create_lost_item_unauthenticated_401_or_403(self, client):
        resp = await client.post(
            "/api/v1/riders/me/lost-items",
            json={
                "description": "Keys",
                "category": "keys",
                "date_lost": str(_TODAY),
                "contact_preference": "phone",
            },
        )
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_create_lost_item_description_too_long_422(self, client, rider_token):
        resp = await client.post(
            "/api/v1/riders/me/lost-items",
            json={
                "description": "x" * 2001,
                "category": "other",
                "date_lost": str(_TODAY),
                "contact_preference": "email",
            },
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_lost_item_invalid_category_422(self, client, rider_token):
        resp = await client.post(
            "/api/v1/riders/me/lost-items",
            json={
                "description": "Something",
                "category": "spaceship",
                "date_lost": str(_TODAY),
                "contact_preference": "app_message",
            },
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_list_lost_items_returns_own(self, client, rider, rider_token, db):
        _insert_lost(db, rider_id=rider.id)
        await db.flush()
        resp = await client.get(
            "/api/v1/riders/me/lost-items",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert all(r["rider_id"] == rider.id for r in data)

    @pytest.mark.asyncio
    async def test_list_lost_items_unauthenticated_401_or_403(self, client):
        resp = await client.get("/api/v1/riders/me/lost-items")
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_get_own_lost_item_200(self, client, rider, rider_token, db):
        report = _insert_lost(db, rider_id=rider.id)
        await db.flush()
        resp = await client.get(
            f"/api/v1/riders/me/lost-items/{report.id}",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == report.id

    @pytest.mark.asyncio
    async def test_get_another_riders_lost_item_403(self, client, rider, db):
        other = User(
            phone="+15557770001",
            name="Other Rider",
            email="other2@test.com",
            password_hash=hash_password("pass"),
            role=UserRole.RIDER,
            is_active=True,
        )
        db.add(other)
        await db.flush()
        other_token = create_access_token(other.id, other.role.value)

        report = _insert_lost(db, rider_id=rider.id)
        await db.flush()

        resp = await client.get(
            f"/api/v1/riders/me/lost-items/{report.id}",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_get_nonexistent_lost_item_404(self, client, rider_token):
        resp = await client.get(
            "/api/v1/riders/me/lost-items/99999",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# API endpoint tests — driver endpoints
# ---------------------------------------------------------------------------


class TestDriverFoundItemAPI:
    @pytest.mark.asyncio
    async def test_create_found_item_201(self, client, driver_user, driver_token):
        resp = await client.post(
            "/api/v1/drivers/me/found-items-v2",
            json={
                "description": "Green umbrella",
                "category": "other",
                "date_found": str(_TODAY),
                "storage_location": "Front seat",
            },
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["driver_id"] == driver_user.id
        assert body["status"] == "pending_match"

    @pytest.mark.asyncio
    async def test_create_found_item_rider_gets_403(self, client, rider_token):
        resp = await client.post(
            "/api/v1/drivers/me/found-items-v2",
            json={
                "description": "Hat",
                "category": "clothing",
                "date_found": str(_TODAY),
                "storage_location": "Back seat",
            },
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_list_found_items_returns_own(self, client, driver_user, driver_token, db):
        _insert_found(db, driver_id=driver_user.id)
        await db.flush()
        resp = await client.get(
            "/api/v1/drivers/me/found-items-v2",
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert all(r["driver_id"] == driver_user.id for r in data)

    @pytest.mark.asyncio
    async def test_list_found_items_rider_gets_403(self, client, rider_token):
        resp = await client.get(
            "/api/v1/drivers/me/found-items-v2",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_get_own_found_item_200(self, client, driver_user, driver_token, db):
        report = _insert_found(db, driver_id=driver_user.id)
        await db.flush()
        resp = await client.get(
            f"/api/v1/drivers/me/found-items-v2/{report.id}",
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == report.id

    @pytest.mark.asyncio
    async def test_get_another_drivers_found_item_403(self, client, driver_user, db):
        other = User(
            phone="+15556660001",
            name="Other Driver",
            email="driver3@test.com",
            password_hash=hash_password("pass"),
            role=UserRole.DRIVER,
            is_active=True,
        )
        db.add(other)
        await db.flush()
        other_token = create_access_token(other.id, other.role.value)

        report = _insert_found(db, driver_id=driver_user.id)
        await db.flush()

        resp = await client.get(
            f"/api/v1/drivers/me/found-items-v2/{report.id}",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# API endpoint tests — admin endpoints
# ---------------------------------------------------------------------------


class TestAdminLostAndFoundAPI:
    @pytest.mark.asyncio
    async def test_admin_list_lost_reports_200(self, client, admin_token, rider, db):
        _insert_lost(db, rider_id=rider.id)
        await db.flush()
        resp = await client.get(
            "/api/v1/admin/lost-and-found/lost-reports",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_non_admin_list_lost_reports_403(self, client, rider_token):
        resp = await client.get(
            "/api/v1/admin/lost-and-found/lost-reports",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_list_lost_filter_by_status(self, client, admin_token, rider, db):
        _insert_lost(db, rider_id=rider.id, status=LafLostItemStatus.OPEN)
        await db.flush()
        resp = await client.get(
            "/api/v1/admin/lost-and-found/lost-reports?status=open",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert all(r["status"] == "open" for r in data)

    @pytest.mark.asyncio
    async def test_admin_list_found_reports_200(self, client, admin_token, driver_user, db):
        _insert_found(db, driver_id=driver_user.id)
        await db.flush()
        resp = await client.get(
            "/api/v1/admin/lost-and-found/found-reports",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_admin_list_found_filter_by_status(self, client, admin_token, driver_user, db):
        _insert_found(db, driver_id=driver_user.id, status=LafFoundItemStatus.PENDING_MATCH)
        await db.flush()
        resp = await client.get(
            "/api/v1/admin/lost-and-found/found-reports?status=pending_match",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert all(r["status"] == "pending_match" for r in data)

    @pytest.mark.asyncio
    async def test_admin_get_lost_report_200(self, client, admin_token, rider, db):
        report = _insert_lost(db, rider_id=rider.id)
        await db.flush()
        resp = await client.get(
            f"/api/v1/admin/lost-and-found/lost-reports/{report.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == report.id

    @pytest.mark.asyncio
    async def test_admin_get_found_report_404(self, client, admin_token):
        resp = await client.get(
            "/api/v1/admin/lost-and-found/found-reports/99999",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_admin_match_reports_200(self, client, admin_token, rider, driver_user, db):
        lost = _insert_lost(db, rider_id=rider.id)
        found = _insert_found(db, driver_id=driver_user.id)
        await db.flush()

        resp = await client.post(
            "/api/v1/admin/lost-and-found/match",
            json={"lost_report_id": lost.id, "found_report_id": found.id},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "matched"
        assert body["matched_found_report_id"] == found.id

    @pytest.mark.asyncio
    async def test_admin_match_already_resolved_409(self, client, admin_token, rider, driver_user, db):
        lost = _insert_lost(db, rider_id=rider.id, status=LafLostItemStatus.CLOSED_NO_MATCH)
        found = _insert_found(db, driver_id=driver_user.id)
        await db.flush()

        resp = await client.post(
            "/api/v1/admin/lost-and-found/match",
            json={"lost_report_id": lost.id, "found_report_id": found.id},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_admin_mark_returned_200(self, client, admin_token, rider, driver_user, db):
        lost = _insert_lost(db, rider_id=rider.id, status=LafLostItemStatus.MATCHED)
        found = _insert_found(db, driver_id=driver_user.id, status=LafFoundItemStatus.MATCHED)
        found.matched_lost_report_id = None  # break the link so no extra load needed
        await db.flush()

        # Point found → lost for the matched link so mark_returned can proceed
        found.matched_lost_report_id = lost.id
        await db.flush()

        resp = await client.post(
            f"/api/v1/admin/lost-and-found/found-reports/{found.id}/mark-returned",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "returned_to_owner"

    @pytest.mark.asyncio
    async def test_admin_mark_returned_not_matched_409(self, client, admin_token, driver_user, db):
        found = _insert_found(db, driver_id=driver_user.id, status=LafFoundItemStatus.PENDING_MATCH)
        await db.flush()
        resp = await client.post(
            f"/api/v1/admin/lost-and-found/found-reports/{found.id}/mark-returned",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_admin_discard_found_200(self, client, admin_token, driver_user, db):
        found = _insert_found(db, driver_id=driver_user.id)
        await db.flush()
        resp = await client.post(
            f"/api/v1/admin/lost-and-found/found-reports/{found.id}/discard",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "discarded"

    @pytest.mark.asyncio
    async def test_admin_discard_already_terminal_409(self, client, admin_token, driver_user, db):
        found = _insert_found(db, driver_id=driver_user.id, status=LafFoundItemStatus.DISCARDED)
        await db.flush()
        resp = await client.post(
            f"/api/v1/admin/lost-and-found/found-reports/{found.id}/discard",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_admin_close_lost_200(self, client, admin_token, rider, db):
        lost = _insert_lost(db, rider_id=rider.id)
        await db.flush()
        resp = await client.post(
            f"/api/v1/admin/lost-and-found/lost-reports/{lost.id}/close",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "closed_no_match"

    @pytest.mark.asyncio
    async def test_admin_close_already_terminal_409(self, client, admin_token, rider, db):
        lost = _insert_lost(db, rider_id=rider.id, status=LafLostItemStatus.CLOSED_NO_MATCH)
        await db.flush()
        resp = await client.post(
            f"/api/v1/admin/lost-and-found/lost-reports/{lost.id}/close",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_admin_list_pagination_limit(self, client, admin_token, rider, db):
        for i in range(5):
            _insert_lost(db, rider_id=rider.id)
        await db.flush()
        resp = await client.get(
            "/api/v1/admin/lost-and-found/lost-reports?limit=2",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert len(resp.json()) <= 2

    @pytest.mark.asyncio
    async def test_admin_list_offset_beyond_results_empty(self, client, admin_token):
        resp = await client.get(
            "/api/v1/admin/lost-and-found/lost-reports?limit=10&offset=10000",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json() == []
