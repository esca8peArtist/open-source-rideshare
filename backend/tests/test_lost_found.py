"""Tests for the lost and found feature.

Covers:
1.  Rider creates lost item report (with and without ride_id)
2.  Driver creates found item report (with and without ride_id)
3.  Rider can view own reports, cannot view another rider's reports
4.  Driver can view own found items, cannot view another driver's items
5.  Admin can view all reports
6.  Admin can match two reports — both change to MATCHED status
7.  Admin can resolve: returned, donated, discarded
8.  Invalid status transitions rejected (REPORTED cannot be returned directly)
9.  Pagination on admin list endpoint
10. Filter by status on admin list
11. Filter by category on admin list
12. Report without authentication returns 401/403
13. Rider cannot access driver found-items endpoint
14. Non-existent report returns 404
15. Rider cannot match reports (forbidden)

Test approach: uses a real in-transaction test DB via the shared conftest fixtures
(same approach as test_tips.py endpoint tests). Service unit tests use AsyncMock
for the DB to avoid a live connection requirement.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.lost_found import LostItemCategory, LostItemReport, LostItemStatus
from app.models.ride import Ride, RideStatus
from app.models.user import User, UserRole
from app.services.auth import create_access_token, hash_password
from app.services.lost_found import (
    LostFoundError,
    create_report,
    get_report,
    list_all_reports,
    list_reports_for_user,
    match_reports,
    resolve_report,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ride(
    ride_id: int = 1,
    rider_id: int = 10,
    driver_id: int = 20,
) -> MagicMock:
    ride = MagicMock()
    ride.id = ride_id
    ride.rider_id = rider_id
    ride.driver_id = driver_id
    ride.status = RideStatus.COMPLETED
    return ride


def _make_report(
    report_id: int = 1,
    reporter_id: int = 10,
    reporter_type: str = "rider",
    status: LostItemStatus = LostItemStatus.REPORTED,
    matched_report_id: int | None = None,
) -> MagicMock:
    r = MagicMock(spec=LostItemReport)
    r.id = report_id
    r.reporter_id = reporter_id
    r.reporter_type = reporter_type
    r.description = "Blue headphones"
    r.category = LostItemCategory.ELECTRONICS
    r.color = "blue"
    r.status = status
    r.matched_report_id = matched_report_id
    r.ride_id = None
    r.resolved_at = None
    r.resolution_notes = None
    r.admin_id = None
    r.contact_phone = None
    r.contact_email = None
    r.created_at = datetime.now(timezone.utc)
    r.updated_at = datetime.now(timezone.utc)
    return r


def _single_result_db(obj) -> AsyncMock:
    """DB mock that returns obj from scalar_one_or_none on a single execute."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = obj
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _multi_execute_db(*objects) -> AsyncMock:
    """DB mock where each execute call returns the next object via scalar_one_or_none."""
    db = AsyncMock()
    results = []
    for obj in objects:
        r = MagicMock()
        r.scalar_one_or_none.return_value = obj
        results.append(r)
    db.execute = AsyncMock(side_effect=results)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _scalars_db(items: list) -> AsyncMock:
    """DB mock where execute returns a result whose scalars().all() = items."""
    db = AsyncMock()
    result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = items
    result.scalars.return_value = scalars_mock
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Service unit tests — create_report
# ---------------------------------------------------------------------------


class TestCreateReport:
    @pytest.mark.asyncio
    async def test_creates_report_without_ride_id(self):
        db = _single_result_db(None)

        report = await create_report(
            db,
            reporter_id=10,
            reporter_type="rider",
            description="Black backpack",
            category=LostItemCategory.BAG,
        )

        db.add.assert_called_once()
        added = db.add.call_args[0][0]
        assert isinstance(added, LostItemReport)
        assert added.reporter_id == 10
        assert added.reporter_type == "rider"
        assert added.category == LostItemCategory.BAG
        assert added.status == LostItemStatus.REPORTED
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_creates_report_with_valid_ride_id(self):
        ride = _make_ride(ride_id=5, rider_id=10)
        db = _single_result_db(ride)

        report = await create_report(
            db,
            reporter_id=10,
            reporter_type="rider",
            description="Sunglasses",
            category=LostItemCategory.OTHER,
            ride_id=5,
        )

        db.add.assert_called_once()
        added = db.add.call_args[0][0]
        assert added.ride_id == 5

    @pytest.mark.asyncio
    async def test_raises_404_when_ride_not_found(self):
        db = _single_result_db(None)

        with pytest.raises(LostFoundError) as exc_info:
            await create_report(
                db,
                reporter_id=10,
                reporter_type="rider",
                description="Phone",
                category=LostItemCategory.ELECTRONICS,
                ride_id=999,
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_raises_403_when_not_participant(self):
        ride = _make_ride(ride_id=5, rider_id=99, driver_id=88)
        db = _single_result_db(ride)

        with pytest.raises(LostFoundError) as exc_info:
            await create_report(
                db,
                reporter_id=10,  # not rider 99 or driver 88
                reporter_type="rider",
                description="Keys",
                category=LostItemCategory.KEYS,
                ride_id=5,
            )
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_driver_reporter_type_stored_correctly(self):
        db = _single_result_db(None)

        await create_report(
            db,
            reporter_id=20,
            reporter_type="driver",
            description="Red jacket",
            category=LostItemCategory.CLOTHING,
        )

        added = db.add.call_args[0][0]
        assert added.reporter_type == "driver"


# ---------------------------------------------------------------------------
# Service unit tests — get_report
# ---------------------------------------------------------------------------


class TestGetReport:
    @pytest.mark.asyncio
    async def test_owner_can_retrieve_own_report(self):
        report = _make_report(report_id=1, reporter_id=10)
        db = _single_result_db(report)

        found = await get_report(db, report_id=1, requesting_user_id=10, is_admin=False)
        assert found is report

    @pytest.mark.asyncio
    async def test_admin_can_retrieve_any_report(self):
        report = _make_report(report_id=1, reporter_id=10)
        db = _single_result_db(report)

        found = await get_report(db, report_id=1, requesting_user_id=999, is_admin=True)
        assert found is report

    @pytest.mark.asyncio
    async def test_non_owner_cannot_retrieve_report(self):
        report = _make_report(report_id=1, reporter_id=10)
        db = _single_result_db(report)

        with pytest.raises(LostFoundError) as exc_info:
            await get_report(db, report_id=1, requesting_user_id=99, is_admin=False)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_returns_404_for_missing_report(self):
        db = _single_result_db(None)

        with pytest.raises(LostFoundError) as exc_info:
            await get_report(db, report_id=999, requesting_user_id=10, is_admin=False)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service unit tests — match_reports
# ---------------------------------------------------------------------------


class TestMatchReports:
    @pytest.mark.asyncio
    async def test_match_sets_both_reports_to_matched(self):
        report_a = _make_report(report_id=1, reporter_id=10)
        report_b = _make_report(report_id=2, reporter_id=20, reporter_type="driver")
        db = _multi_execute_db(report_a, report_b)

        with patch("app.services.lost_found._notify_match", new_callable=AsyncMock):
            a, b = await match_reports(db, report_id=1, matched_report_id=2, admin_id=99)

        assert a.status == LostItemStatus.MATCHED
        assert b.status == LostItemStatus.MATCHED
        assert a.matched_report_id == 2
        assert b.matched_report_id == 1
        assert a.admin_id == 99
        assert b.admin_id == 99

    @pytest.mark.asyncio
    async def test_match_raises_400_for_self_match(self):
        db = AsyncMock()

        with pytest.raises(LostFoundError) as exc_info:
            await match_reports(db, report_id=1, matched_report_id=1, admin_id=99)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_match_raises_404_when_first_report_missing(self):
        db = _single_result_db(None)

        with pytest.raises(LostFoundError) as exc_info:
            await match_reports(db, report_id=999, matched_report_id=2, admin_id=99)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_match_raises_404_when_second_report_missing(self):
        report_a = _make_report(report_id=1)
        db = _multi_execute_db(report_a, None)

        with pytest.raises(LostFoundError) as exc_info:
            await match_reports(db, report_id=1, matched_report_id=999, admin_id=99)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_match_raises_409_when_report_already_terminal(self):
        report_a = _make_report(report_id=1, status=LostItemStatus.RETURNED)
        report_b = _make_report(report_id=2, reporter_type="driver")
        db = _multi_execute_db(report_a, report_b)

        with pytest.raises(LostFoundError) as exc_info:
            await match_reports(db, report_id=1, matched_report_id=2, admin_id=99)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_match_notifications_failure_does_not_raise(self):
        report_a = _make_report(report_id=1)
        report_b = _make_report(report_id=2, reporter_type="driver")
        db = _multi_execute_db(report_a, report_b)

        with patch(
            "app.services.lost_found._notify_match",
            new_callable=AsyncMock,
            side_effect=Exception("notification down"),
        ):
            # Should not raise
            await match_reports(db, report_id=1, matched_report_id=2, admin_id=99)


# ---------------------------------------------------------------------------
# Service unit tests — resolve_report
# ---------------------------------------------------------------------------


class TestResolveReport:
    @pytest.mark.asyncio
    async def test_resolve_matched_report_as_returned(self):
        report = _make_report(report_id=1, status=LostItemStatus.MATCHED)
        db = _single_result_db(report)

        resolved = await resolve_report(
            db, report_id=1, new_status=LostItemStatus.RETURNED, admin_id=99
        )

        assert resolved.status == LostItemStatus.RETURNED
        assert resolved.admin_id == 99
        assert resolved.resolved_at is not None

    @pytest.mark.asyncio
    async def test_resolve_as_donated(self):
        report = _make_report(report_id=1, status=LostItemStatus.REPORTED)
        db = _single_result_db(report)

        resolved = await resolve_report(
            db, report_id=1, new_status=LostItemStatus.DONATED, admin_id=99
        )
        assert resolved.status == LostItemStatus.DONATED

    @pytest.mark.asyncio
    async def test_resolve_as_discarded(self):
        report = _make_report(report_id=1, status=LostItemStatus.REPORTED)
        db = _single_result_db(report)

        resolved = await resolve_report(
            db, report_id=1, new_status=LostItemStatus.DISCARDED, admin_id=99
        )
        assert resolved.status == LostItemStatus.DISCARDED

    @pytest.mark.asyncio
    async def test_resolve_notes_stored(self):
        report = _make_report(report_id=1, status=LostItemStatus.REPORTED)
        db = _single_result_db(report)

        resolved = await resolve_report(
            db,
            report_id=1,
            new_status=LostItemStatus.DONATED,
            admin_id=99,
            resolution_notes="Donated to local charity",
        )
        assert resolved.resolution_notes == "Donated to local charity"

    @pytest.mark.asyncio
    async def test_reported_report_cannot_be_returned_directly(self):
        """REPORTED → RETURNED is invalid; must be MATCHED first."""
        report = _make_report(report_id=1, status=LostItemStatus.REPORTED)
        db = _single_result_db(report)

        with pytest.raises(LostFoundError) as exc_info:
            await resolve_report(
                db, report_id=1, new_status=LostItemStatus.RETURNED, admin_id=99
            )
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_already_terminal_report_cannot_be_resolved_again(self):
        report = _make_report(report_id=1, status=LostItemStatus.RETURNED)
        db = _single_result_db(report)

        with pytest.raises(LostFoundError) as exc_info:
            await resolve_report(
                db, report_id=1, new_status=LostItemStatus.DONATED, admin_id=99
            )
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_resolve_raises_404_for_missing_report(self):
        db = _single_result_db(None)

        with pytest.raises(LostFoundError) as exc_info:
            await resolve_report(
                db, report_id=999, new_status=LostItemStatus.DONATED, admin_id=99
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_invalid_status_raises_422(self):
        db = _single_result_db(None)

        with pytest.raises(LostFoundError) as exc_info:
            await resolve_report(
                db, report_id=1, new_status=LostItemStatus.REPORTED, admin_id=99
            )
        assert exc_info.value.status_code == 422


# ---------------------------------------------------------------------------
# API endpoint tests — rider endpoints
# ---------------------------------------------------------------------------


def _ride_in_db(db, rider_id: int, driver_id: int) -> Ride:
    """Insert a completed ride into the test database session and return it."""
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


class TestRiderReportLostItem:
    @pytest.mark.asyncio
    async def test_rider_creates_report_without_ride_id(self, client, rider, rider_token):
        resp = await client.post(
            "/api/v1/lost-found/report",
            json={
                "description": "Blue wireless headphones",
                "category": "electronics",
            },
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["description"] == "Blue wireless headphones"
        assert body["category"] == "electronics"
        assert body["status"] == "reported"
        assert body["reporter_type"] == "rider"

    @pytest.mark.asyncio
    async def test_rider_creates_report_with_ride_id(self, client, rider, rider_token, driver_user, db):
        ride = _ride_in_db(db, rider_id=rider.id, driver_id=driver_user.id)
        await db.flush()

        resp = await client.post(
            "/api/v1/lost-found/report",
            json={
                "ride_id": ride.id,
                "description": "Red umbrella",
                "category": "other",
            },
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 201
        assert resp.json()["ride_id"] == ride.id

    @pytest.mark.asyncio
    async def test_report_with_nonexistent_ride_returns_404(self, client, rider, rider_token):
        resp = await client.post(
            "/api/v1/lost-found/report",
            json={
                "ride_id": 99999,
                "description": "Something",
                "category": "other",
            },
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_unauthenticated_report_returns_401_or_403(self, client):
        resp = await client.post(
            "/api/v1/lost-found/report",
            json={"description": "Keys", "category": "keys"},
        )
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_description_too_long_returns_422(self, client, rider, rider_token):
        resp = await client.post(
            "/api/v1/lost-found/report",
            json={"description": "x" * 501, "category": "other"},
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_category_returns_422(self, client, rider, rider_token):
        resp = await client.post(
            "/api/v1/lost-found/report",
            json={"description": "Something", "category": "spaceship"},
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 422


class TestRiderListMyReports:
    @pytest.mark.asyncio
    async def test_rider_can_list_own_reports(self, client, rider, rider_token, db):
        # Create a report directly
        report = LostItemReport(
            reporter_id=rider.id,
            reporter_type="rider",
            description="Brown wallet",
            category=LostItemCategory.BAG,
            status=LostItemStatus.REPORTED,
        )
        db.add(report)
        await db.flush()

        resp = await client.get(
            "/api/v1/lost-found/my-reports",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert any(r["description"] == "Brown wallet" for r in data)

    @pytest.mark.asyncio
    async def test_unauthenticated_list_returns_401_or_403(self, client):
        resp = await client.get("/api/v1/lost-found/my-reports")
        assert resp.status_code in (401, 403)


class TestRiderGetReport:
    @pytest.mark.asyncio
    async def test_rider_can_get_own_report(self, client, rider, rider_token, db):
        report = LostItemReport(
            reporter_id=rider.id,
            reporter_type="rider",
            description="Silver ring",
            category=LostItemCategory.JEWELRY,
            status=LostItemStatus.REPORTED,
        )
        db.add(report)
        await db.flush()

        resp = await client.get(
            f"/api/v1/lost-found/{report.id}",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == report.id

    @pytest.mark.asyncio
    async def test_rider_cannot_get_another_riders_report(self, client, rider, db):
        # Create a second rider
        other = User(
            phone="+15559990001",
            name="Other Rider",
            email="other@test.com",
            password_hash=hash_password("pass"),
            role=UserRole.RIDER,
            is_active=True,
        )
        db.add(other)
        await db.flush()
        other_token = create_access_token(other.id, other.role.value)

        report = LostItemReport(
            reporter_id=rider.id,
            reporter_type="rider",
            description="Laptop",
            category=LostItemCategory.ELECTRONICS,
            status=LostItemStatus.REPORTED,
        )
        db.add(report)
        await db.flush()

        resp = await client.get(
            f"/api/v1/lost-found/{report.id}",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_get_nonexistent_report_returns_404(self, client, rider, rider_token):
        resp = await client.get(
            "/api/v1/lost-found/99999",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# API endpoint tests — driver endpoints
# ---------------------------------------------------------------------------


class TestDriverFoundItems:
    @pytest.mark.asyncio
    async def test_driver_creates_found_report_without_ride(
        self, client, driver_user, driver_token
    ):
        resp = await client.post(
            "/api/v1/drivers/me/found-items",
            json={"description": "Green umbrella", "category": "other"},
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["reporter_type"] == "driver"
        assert body["description"] == "Green umbrella"

    @pytest.mark.asyncio
    async def test_driver_creates_found_report_with_ride_id(
        self, client, driver_user, driver_token, rider, db
    ):
        ride = _ride_in_db(db, rider_id=rider.id, driver_id=driver_user.id)
        await db.flush()

        resp = await client.post(
            "/api/v1/drivers/me/found-items",
            json={
                "ride_id": ride.id,
                "description": "Phone charger",
                "category": "electronics",
            },
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert resp.status_code == 201
        assert resp.json()["ride_id"] == ride.id

    @pytest.mark.asyncio
    async def test_rider_cannot_access_driver_found_items_endpoint(
        self, client, rider_token
    ):
        resp = await client.post(
            "/api/v1/drivers/me/found-items",
            json={"description": "Hat", "category": "clothing"},
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_driver_can_list_own_found_items(
        self, client, driver_user, driver_token, db
    ):
        report = LostItemReport(
            reporter_id=driver_user.id,
            reporter_type="driver",
            description="Purple scarf",
            category=LostItemCategory.CLOTHING,
            status=LostItemStatus.REPORTED,
        )
        db.add(report)
        await db.flush()

        resp = await client.get(
            "/api/v1/drivers/me/found-items",
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert any(r["description"] == "Purple scarf" for r in data)

    @pytest.mark.asyncio
    async def test_driver_found_items_only_shows_own_reports(
        self, client, driver_user, driver_token, rider, db
    ):
        """Driver list should not contain reports made by other users."""
        other_driver = User(
            phone="+15558880001",
            name="Other Driver",
            email="driver2@test.com",
            password_hash=hash_password("pass"),
            role=UserRole.DRIVER,
            is_active=True,
        )
        db.add(other_driver)
        await db.flush()

        # Report by other driver
        other_report = LostItemReport(
            reporter_id=other_driver.id,
            reporter_type="driver",
            description="White gloves",
            category=LostItemCategory.CLOTHING,
            status=LostItemStatus.REPORTED,
        )
        db.add(other_report)
        await db.flush()

        resp = await client.get(
            "/api/v1/drivers/me/found-items",
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert all(r["reporter_id"] == driver_user.id for r in data)

    @pytest.mark.asyncio
    async def test_rider_cannot_list_driver_found_items(self, client, rider_token):
        resp = await client.get(
            "/api/v1/drivers/me/found-items",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# API endpoint tests — admin endpoints
# ---------------------------------------------------------------------------


class TestAdminListReports:
    @pytest.mark.asyncio
    async def test_admin_can_list_all_reports(
        self, client, admin_user, admin_token, rider, db
    ):
        report = LostItemReport(
            reporter_id=rider.id,
            reporter_type="rider",
            description="Black sunglasses",
            category=LostItemCategory.OTHER,
            status=LostItemStatus.REPORTED,
        )
        db.add(report)
        await db.flush()

        resp = await client.get(
            "/api/v1/admin/lost-found",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert any(r["description"] == "Black sunglasses" for r in data)

    @pytest.mark.asyncio
    async def test_non_admin_cannot_access_admin_list(self, client, rider_token):
        resp = await client.get(
            "/api/v1/admin/lost-found",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_list_filter_by_status(
        self, client, admin_token, rider, driver_user, db
    ):
        matched_report = LostItemReport(
            reporter_id=rider.id,
            reporter_type="rider",
            description="Matched item",
            category=LostItemCategory.ELECTRONICS,
            status=LostItemStatus.MATCHED,
        )
        reported_report = LostItemReport(
            reporter_id=driver_user.id,
            reporter_type="driver",
            description="Reported item",
            category=LostItemCategory.CLOTHING,
            status=LostItemStatus.REPORTED,
        )
        db.add(matched_report)
        db.add(reported_report)
        await db.flush()

        resp = await client.get(
            "/api/v1/admin/lost-found?status=matched",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert all(r["status"] == "matched" for r in data)

    @pytest.mark.asyncio
    async def test_admin_list_filter_by_category(
        self, client, admin_token, rider, db
    ):
        keys_report = LostItemReport(
            reporter_id=rider.id,
            reporter_type="rider",
            description="House keys",
            category=LostItemCategory.KEYS,
            status=LostItemStatus.REPORTED,
        )
        db.add(keys_report)
        await db.flush()

        resp = await client.get(
            "/api/v1/admin/lost-found?category=keys",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert all(r["category"] == "keys" for r in data)

    @pytest.mark.asyncio
    async def test_admin_list_pagination(
        self, client, admin_token, rider, db
    ):
        # Insert 5 reports
        for i in range(5):
            r = LostItemReport(
                reporter_id=rider.id,
                reporter_type="rider",
                description=f"Item {i}",
                category=LostItemCategory.OTHER,
                status=LostItemStatus.REPORTED,
            )
            db.add(r)
        await db.flush()

        resp = await client.get(
            "/api/v1/admin/lost-found?limit=2&offset=0",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert len(resp.json()) <= 2

    @pytest.mark.asyncio
    async def test_admin_list_pagination_offset(
        self, client, admin_token, rider, db
    ):
        """offset=1000 should return an empty list, not an error."""
        resp = await client.get(
            "/api/v1/admin/lost-found?limit=10&offset=1000",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json() == []


class TestAdminGetReport:
    @pytest.mark.asyncio
    async def test_admin_can_get_any_report(
        self, client, admin_token, rider, db
    ):
        report = LostItemReport(
            reporter_id=rider.id,
            reporter_type="rider",
            description="Passport",
            category=LostItemCategory.DOCUMENTS,
            status=LostItemStatus.REPORTED,
        )
        db.add(report)
        await db.flush()

        resp = await client.get(
            f"/api/v1/admin/lost-found/{report.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == report.id

    @pytest.mark.asyncio
    async def test_admin_get_nonexistent_returns_404(self, client, admin_token):
        resp = await client.get(
            "/api/v1/admin/lost-found/99999",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404


class TestAdminMatchReports:
    @pytest.mark.asyncio
    async def test_admin_can_match_two_reports(
        self, client, admin_token, rider, driver_user, db
    ):
        lost = LostItemReport(
            reporter_id=rider.id,
            reporter_type="rider",
            description="Gold watch",
            category=LostItemCategory.JEWELRY,
            status=LostItemStatus.REPORTED,
        )
        found = LostItemReport(
            reporter_id=driver_user.id,
            reporter_type="driver",
            description="Gold watch",
            category=LostItemCategory.JEWELRY,
            status=LostItemStatus.REPORTED,
        )
        db.add(lost)
        db.add(found)
        await db.flush()

        resp = await client.post(
            f"/api/v1/admin/lost-found/{lost.id}/match",
            json={"matched_report_id": found.id},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "matched"
        assert body["matched_report_id"] == found.id

    @pytest.mark.asyncio
    async def test_match_updates_both_reports(
        self, client, admin_token, rider, driver_user, db
    ):
        lost = LostItemReport(
            reporter_id=rider.id,
            reporter_type="rider",
            description="Grey scarf",
            category=LostItemCategory.CLOTHING,
            status=LostItemStatus.REPORTED,
        )
        found = LostItemReport(
            reporter_id=driver_user.id,
            reporter_type="driver",
            description="Grey scarf",
            category=LostItemCategory.CLOTHING,
            status=LostItemStatus.REPORTED,
        )
        db.add(lost)
        db.add(found)
        await db.flush()
        lost_id, found_id = lost.id, found.id

        await client.post(
            f"/api/v1/admin/lost-found/{lost_id}/match",
            json={"matched_report_id": found_id},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        # Fetch the found report via admin endpoint to verify its status
        resp = await client.get(
            f"/api/v1/admin/lost-found/{found_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.json()["status"] == "matched"

    @pytest.mark.asyncio
    async def test_rider_cannot_match_reports(
        self, client, rider, rider_token, driver_user, db
    ):
        lost = LostItemReport(
            reporter_id=rider.id,
            reporter_type="rider",
            description="Item A",
            category=LostItemCategory.OTHER,
            status=LostItemStatus.REPORTED,
        )
        found = LostItemReport(
            reporter_id=driver_user.id,
            reporter_type="driver",
            description="Item A",
            category=LostItemCategory.OTHER,
            status=LostItemStatus.REPORTED,
        )
        db.add(lost)
        db.add(found)
        await db.flush()

        resp = await client.post(
            f"/api/v1/admin/lost-found/{lost.id}/match",
            json={"matched_report_id": found.id},
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_match_nonexistent_report_returns_404(
        self, client, admin_token
    ):
        resp = await client.post(
            "/api/v1/admin/lost-found/99999/match",
            json={"matched_report_id": 1},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_match_to_self_returns_400(
        self, client, admin_token, rider, db
    ):
        report = LostItemReport(
            reporter_id=rider.id,
            reporter_type="rider",
            description="Watch",
            category=LostItemCategory.JEWELRY,
            status=LostItemStatus.REPORTED,
        )
        db.add(report)
        await db.flush()

        resp = await client.post(
            f"/api/v1/admin/lost-found/{report.id}/match",
            json={"matched_report_id": report.id},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 400


class TestAdminResolveReport:
    @pytest.mark.asyncio
    async def test_admin_resolves_matched_report_as_returned(
        self, client, admin_token, rider, driver_user, db
    ):
        report = LostItemReport(
            reporter_id=rider.id,
            reporter_type="rider",
            description="Blue backpack",
            category=LostItemCategory.BAG,
            status=LostItemStatus.MATCHED,
        )
        db.add(report)
        await db.flush()

        resp = await client.post(
            f"/api/v1/admin/lost-found/{report.id}/resolve",
            json={"status": "returned", "resolution_notes": "Returned at office"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "returned"
        assert body["resolution_notes"] == "Returned at office"

    @pytest.mark.asyncio
    async def test_admin_resolves_report_as_donated(
        self, client, admin_token, rider, db
    ):
        report = LostItemReport(
            reporter_id=rider.id,
            reporter_type="rider",
            description="Old coat",
            category=LostItemCategory.CLOTHING,
            status=LostItemStatus.REPORTED,
        )
        db.add(report)
        await db.flush()

        resp = await client.post(
            f"/api/v1/admin/lost-found/{report.id}/resolve",
            json={"status": "donated"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "donated"

    @pytest.mark.asyncio
    async def test_admin_resolves_report_as_discarded(
        self, client, admin_token, rider, db
    ):
        report = LostItemReport(
            reporter_id=rider.id,
            reporter_type="rider",
            description="Broken umbrella",
            category=LostItemCategory.OTHER,
            status=LostItemStatus.REPORTED,
        )
        db.add(report)
        await db.flush()

        resp = await client.post(
            f"/api/v1/admin/lost-found/{report.id}/resolve",
            json={"status": "discarded"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "discarded"

    @pytest.mark.asyncio
    async def test_reported_report_cannot_be_returned_directly(
        self, client, admin_token, rider, db
    ):
        report = LostItemReport(
            reporter_id=rider.id,
            reporter_type="rider",
            description="Tablet",
            category=LostItemCategory.ELECTRONICS,
            status=LostItemStatus.REPORTED,
        )
        db.add(report)
        await db.flush()

        resp = await client.post(
            f"/api/v1/admin/lost-found/{report.id}/resolve",
            json={"status": "returned"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_resolve_with_invalid_status_returns_422(
        self, client, admin_token, rider, db
    ):
        report = LostItemReport(
            reporter_id=rider.id,
            reporter_type="rider",
            description="Keys",
            category=LostItemCategory.KEYS,
            status=LostItemStatus.REPORTED,
        )
        db.add(report)
        await db.flush()

        resp = await client.post(
            f"/api/v1/admin/lost-found/{report.id}/resolve",
            json={"status": "reported"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_resolve_nonexistent_report_returns_404(
        self, client, admin_token
    ):
        resp = await client.post(
            "/api/v1/admin/lost-found/99999/resolve",
            json={"status": "donated"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_rider_cannot_resolve_report(
        self, client, rider, rider_token, db
    ):
        report = LostItemReport(
            reporter_id=rider.id,
            reporter_type="rider",
            description="Document folder",
            category=LostItemCategory.DOCUMENTS,
            status=LostItemStatus.REPORTED,
        )
        db.add(report)
        await db.flush()

        resp = await client.post(
            f"/api/v1/admin/lost-found/{report.id}/resolve",
            json={"status": "donated"},
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 403
