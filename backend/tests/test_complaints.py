"""Tests for the complaint and dispute management system.

Service unit tests (AsyncMock DB, no live connection needed):
- file_complaint: success with/without ride_id, self-complaint, short description,
  ride not found, not a ride participant
- get_my_complaints: returns filed-by-me only, empty list, pagination
- get_complaints_against_me: returns against-me, admin_notes masked unless terminal
- admin_list_complaints: all complaints, status filter
- admin_get_complaint: found, not found
- admin_update_complaint: reviewing (no notes), resolve, dismiss, re-resolve blocked,
  cannot revert to pending

API endpoint tests (real DB via conftest fixtures):
- POST /complaints: success without ride_id, success with ride_id, self-complaint,
  description too short, unauthenticated
- GET /complaints/me/filed: returns own, empty, pagination
- GET /complaints/me/received: returns against-me, admin_notes hidden until resolved
- GET /admin/complaints: returns all, status filter
- GET /admin/complaints/{id}: success, not found
- PUT /admin/complaints/{id}: set reviewing, resolve with notes, dismiss with notes,
  re-resolve blocked, admin_notes visible after resolution, non-admin rejected
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.complaint import Complaint, ComplaintCategory, ComplaintStatus
from app.models.ride import RideStatus
from app.models.user import UserRole
from app.schemas.complaint import ComplaintCreate, ComplaintUpdateAdmin
from app.services.auth import create_access_token, hash_password
from app.services.complaints import (
    ComplaintError,
    admin_get_complaint,
    admin_list_complaints,
    admin_update_complaint,
    file_complaint,
    get_complaints_against_me,
    get_my_complaints,
)


# ---------------------------------------------------------------------------
# Helpers — mock factories
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


def _make_complaint(
    complaint_id: int = 1,
    filed_by_user_id: int = 10,
    against_user_id: int = 20,
    ride_id: int | None = None,
    status: ComplaintStatus = ComplaintStatus.PENDING,
    admin_notes: str | None = None,
    resolved_by_admin_id: int | None = None,
) -> MagicMock:
    c = MagicMock(spec=Complaint)
    c.id = complaint_id
    c.filed_by_user_id = filed_by_user_id
    c.against_user_id = against_user_id
    c.ride_id = ride_id
    c.category = ComplaintCategory.HARASSMENT
    c.description = "This is a test complaint with enough detail"
    c.status = status
    c.admin_notes = admin_notes
    c.resolved_by_admin_id = resolved_by_admin_id
    c.created_at = datetime.now(timezone.utc)
    c.updated_at = datetime.now(timezone.utc)
    return c


def _single_result_db(obj) -> AsyncMock:
    """DB mock returning obj via scalar_one_or_none on one execute call."""
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
    """DB mock where successive execute calls return successive scalar_one_or_none values."""
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


def _ride_fixture(rider_id: int, driver_id: int, status: RideStatus = RideStatus.COMPLETED):
    return dict(
        rider_id=rider_id,
        driver_id=driver_id,
        status=status,
        pickup_location="SRID=4326;POINT(-73.9857 40.7484)",
        dropoff_location="SRID=4326;POINT(-73.9857 40.7484)",
        pickup_address="123 Main St",
        dropoff_address="456 Oak Ave",
        estimated_fare=12.0,
        actual_fare=12.0,
    )


# ---------------------------------------------------------------------------
# Service unit tests — file_complaint
# ---------------------------------------------------------------------------


class TestFileComplaint:
    @pytest.mark.asyncio
    async def test_creates_complaint_without_ride_id(self):
        db = _single_result_db(None)
        data = ComplaintCreate(
            against_user_id=20,
            category=ComplaintCategory.HARASSMENT,
            description="This is a detailed complaint description.",
        )

        complaint = await file_complaint(db, filed_by_user_id=10, data=data)

        db.add.assert_called_once()
        added = db.add.call_args[0][0]
        assert isinstance(added, Complaint)
        assert added.filed_by_user_id == 10
        assert added.against_user_id == 20
        assert added.status == ComplaintStatus.PENDING
        assert added.ride_id is None
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_creates_complaint_with_valid_ride_id(self):
        ride = _make_ride(ride_id=5, rider_id=10, driver_id=20)
        db = _single_result_db(ride)
        data = ComplaintCreate(
            against_user_id=20,
            ride_id=5,
            category=ComplaintCategory.UNSAFE_DRIVING,
            description="Driver was swerving dangerously throughout the trip.",
        )

        complaint = await file_complaint(db, filed_by_user_id=10, data=data)

        db.add.assert_called_once()
        added = db.add.call_args[0][0]
        assert added.ride_id == 5
        assert added.filed_by_user_id == 10

    @pytest.mark.asyncio
    async def test_rejects_self_complaint(self):
        db = AsyncMock()
        data = ComplaintCreate(
            against_user_id=10,
            category=ComplaintCategory.OTHER,
            description="Trying to complain about myself here.",
        )

        with pytest.raises(ComplaintError) as exc_info:
            await file_complaint(db, filed_by_user_id=10, data=data)
        assert exc_info.value.status_code == 400
        assert "yourself" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_rejects_when_ride_not_found(self):
        db = _single_result_db(None)
        data = ComplaintCreate(
            against_user_id=20,
            ride_id=999,
            category=ComplaintCategory.FRAUD,
            description="Ride does not exist but complaint references it.",
        )

        with pytest.raises(ComplaintError) as exc_info:
            await file_complaint(db, filed_by_user_id=10, data=data)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_rejects_when_filer_not_in_ride(self):
        ride = _make_ride(ride_id=5, rider_id=99, driver_id=20)
        db = _single_result_db(ride)
        data = ComplaintCreate(
            against_user_id=20,
            ride_id=5,
            category=ComplaintCategory.HARASSMENT,
            description="Filer was not part of this ride at all.",
        )

        with pytest.raises(ComplaintError) as exc_info:
            await file_complaint(db, filed_by_user_id=10, data=data)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_rejects_when_against_user_not_in_ride(self):
        ride = _make_ride(ride_id=5, rider_id=10, driver_id=20)
        db = _single_result_db(ride)
        data = ComplaintCreate(
            against_user_id=999,
            ride_id=5,
            category=ComplaintCategory.HARASSMENT,
            description="Complaining about someone not in this ride.",
        )

        with pytest.raises(ComplaintError) as exc_info:
            await file_complaint(db, filed_by_user_id=10, data=data)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Service unit tests — get_my_complaints
# ---------------------------------------------------------------------------


class TestGetMyComplaints:
    @pytest.mark.asyncio
    async def test_returns_list_of_complaints(self):
        c1 = _make_complaint(complaint_id=1, filed_by_user_id=10)
        c2 = _make_complaint(complaint_id=2, filed_by_user_id=10)
        db = _scalars_db([c1, c2])

        result = await get_my_complaints(db, user_id=10)

        assert len(result) == 2
        assert result[0].id == 1

    @pytest.mark.asyncio
    async def test_returns_empty_list(self):
        db = _scalars_db([])
        result = await get_my_complaints(db, user_id=10)
        assert result == []

    @pytest.mark.asyncio
    async def test_passes_pagination_params(self):
        db = _scalars_db([])
        await get_my_complaints(db, user_id=10, skip=40, limit=10)
        # Verify execute was called — pagination is passed through the ORM query
        db.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# Service unit tests — get_complaints_against_me
# ---------------------------------------------------------------------------


class TestGetComplaintsAgainstMe:
    @pytest.mark.asyncio
    async def test_returns_complaints_against_user(self):
        c = _make_complaint(against_user_id=20, status=ComplaintStatus.PENDING)
        db = _scalars_db([c])

        result = await get_complaints_against_me(db, user_id=20)

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_admin_notes_hidden_for_pending(self):
        c = _make_complaint(
            against_user_id=20,
            status=ComplaintStatus.PENDING,
            admin_notes="Internal investigation notes",
        )
        db = _scalars_db([c])

        result = await get_complaints_against_me(db, user_id=20)

        assert result[0].admin_notes is None

    @pytest.mark.asyncio
    async def test_admin_notes_hidden_for_reviewing(self):
        c = _make_complaint(
            against_user_id=20,
            status=ComplaintStatus.REVIEWING,
            admin_notes="Still investigating",
        )
        db = _scalars_db([c])

        result = await get_complaints_against_me(db, user_id=20)

        assert result[0].admin_notes is None

    @pytest.mark.asyncio
    async def test_admin_notes_visible_when_resolved(self):
        c = _make_complaint(
            against_user_id=20,
            status=ComplaintStatus.RESOLVED,
            admin_notes="Complaint was substantiated",
        )
        db = _scalars_db([c])

        result = await get_complaints_against_me(db, user_id=20)

        assert result[0].admin_notes == "Complaint was substantiated"

    @pytest.mark.asyncio
    async def test_admin_notes_visible_when_dismissed(self):
        c = _make_complaint(
            against_user_id=20,
            status=ComplaintStatus.DISMISSED,
            admin_notes="Insufficient evidence",
        )
        db = _scalars_db([c])

        result = await get_complaints_against_me(db, user_id=20)

        assert result[0].admin_notes == "Insufficient evidence"


# ---------------------------------------------------------------------------
# Service unit tests — admin_list_complaints
# ---------------------------------------------------------------------------


class TestAdminListComplaints:
    @pytest.mark.asyncio
    async def test_returns_all_complaints_without_filter(self):
        complaints = [_make_complaint(complaint_id=i) for i in range(3)]
        db = _scalars_db(complaints)

        result = await admin_list_complaints(db)

        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_passes_status_filter(self):
        db = _scalars_db([])
        await admin_list_complaints(db, status=ComplaintStatus.PENDING)
        db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_empty_list(self):
        db = _scalars_db([])
        result = await admin_list_complaints(db)
        assert result == []


# ---------------------------------------------------------------------------
# Service unit tests — admin_get_complaint
# ---------------------------------------------------------------------------


class TestAdminGetComplaint:
    @pytest.mark.asyncio
    async def test_returns_complaint_when_found(self):
        c = _make_complaint(complaint_id=42)
        db = _single_result_db(c)

        result = await admin_get_complaint(db, complaint_id=42)

        assert result.id == 42

    @pytest.mark.asyncio
    async def test_raises_404_when_not_found(self):
        db = _single_result_db(None)

        with pytest.raises(ComplaintError) as exc_info:
            await admin_get_complaint(db, complaint_id=999)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service unit tests — admin_update_complaint
# ---------------------------------------------------------------------------


class TestAdminUpdateComplaint:
    @pytest.mark.asyncio
    async def test_sets_to_reviewing(self):
        c = _make_complaint(status=ComplaintStatus.PENDING)
        db = _single_result_db(c)
        update = ComplaintUpdateAdmin(status=ComplaintStatus.REVIEWING)

        result = await admin_update_complaint(db, complaint_id=1, admin_id=99, data=update)

        assert result.status == ComplaintStatus.REVIEWING
        assert result.resolved_by_admin_id is None  # not terminal yet
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_resolves_with_notes(self):
        c = _make_complaint(status=ComplaintStatus.REVIEWING)
        db = _single_result_db(c)
        update = ComplaintUpdateAdmin(
            status=ComplaintStatus.RESOLVED, admin_notes="Complaint confirmed by evidence."
        )

        result = await admin_update_complaint(db, complaint_id=1, admin_id=99, data=update)

        assert result.status == ComplaintStatus.RESOLVED
        assert result.admin_notes == "Complaint confirmed by evidence."
        assert result.resolved_by_admin_id == 99

    @pytest.mark.asyncio
    async def test_dismisses_with_notes(self):
        c = _make_complaint(status=ComplaintStatus.REVIEWING)
        db = _single_result_db(c)
        update = ComplaintUpdateAdmin(
            status=ComplaintStatus.DISMISSED, admin_notes="No supporting evidence found."
        )

        result = await admin_update_complaint(db, complaint_id=1, admin_id=99, data=update)

        assert result.status == ComplaintStatus.DISMISSED
        assert result.resolved_by_admin_id == 99

    @pytest.mark.asyncio
    async def test_cannot_update_already_resolved(self):
        c = _make_complaint(status=ComplaintStatus.RESOLVED)
        db = _single_result_db(c)
        update = ComplaintUpdateAdmin(status=ComplaintStatus.REVIEWING)

        with pytest.raises(ComplaintError) as exc_info:
            await admin_update_complaint(db, complaint_id=1, admin_id=99, data=update)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_cannot_update_already_dismissed(self):
        c = _make_complaint(status=ComplaintStatus.DISMISSED)
        db = _single_result_db(c)
        update = ComplaintUpdateAdmin(status=ComplaintStatus.REVIEWING)

        with pytest.raises(ComplaintError) as exc_info:
            await admin_update_complaint(db, complaint_id=1, admin_id=99, data=update)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_cannot_set_status_to_pending(self):
        c = _make_complaint(status=ComplaintStatus.REVIEWING)
        db = _single_result_db(c)
        update = ComplaintUpdateAdmin(status=ComplaintStatus.PENDING)

        with pytest.raises(ComplaintError) as exc_info:
            await admin_update_complaint(db, complaint_id=1, admin_id=99, data=update)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_raises_404_for_missing_complaint(self):
        db = _single_result_db(None)
        update = ComplaintUpdateAdmin(status=ComplaintStatus.REVIEWING)

        with pytest.raises(ComplaintError) as exc_info:
            await admin_update_complaint(db, complaint_id=999, admin_id=99, data=update)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# API endpoint tests — POST /complaints
# ---------------------------------------------------------------------------


class TestCreateComplaintEndpoint:
    @pytest.mark.asyncio
    async def test_creates_complaint_without_ride(self, client, rider, driver_user, rider_token):
        resp = await client.post(
            "/api/v1/complaints",
            json={
                "against_user_id": driver_user.id,
                "category": "harassment",
                "description": "The driver was very rude and unprofessional during the entire trip.",
            },
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["filed_by_user_id"] == rider.id
        assert body["against_user_id"] == driver_user.id
        assert body["status"] == "pending"
        assert body["category"] == "harassment"

    @pytest.mark.asyncio
    async def test_creates_complaint_with_ride_id(
        self, client, rider, driver_user, rider_token, db
    ):
        from app.models.ride import Ride

        ride = Ride(**_ride_fixture(rider.id, driver_user.id))
        db.add(ride)
        await db.flush()

        resp = await client.post(
            "/api/v1/complaints",
            json={
                "against_user_id": driver_user.id,
                "ride_id": ride.id,
                "category": "unsafe_driving",
                "description": "Driver ran multiple red lights and was speeding dangerously.",
            },
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["ride_id"] == ride.id

    @pytest.mark.asyncio
    async def test_cannot_complain_against_self(self, client, rider, rider_token):
        resp = await client.post(
            "/api/v1/complaints",
            json={
                "against_user_id": rider.id,
                "category": "other",
                "description": "Attempting to file a complaint against myself.",
            },
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 400
        assert "yourself" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_rejects_short_description(self, client, rider, driver_user, rider_token):
        resp = await client.post(
            "/api/v1/complaints",
            json={
                "against_user_id": driver_user.id,
                "category": "other",
                "description": "Too short",  # under 20 chars
            },
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_unauthenticated_request_rejected(self, client, driver_user):
        resp = await client.post(
            "/api/v1/complaints",
            json={
                "against_user_id": driver_user.id,
                "category": "other",
                "description": "No auth token included in this request at all.",
            },
        )
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_rejects_invalid_ride_id(self, client, rider, driver_user, rider_token):
        resp = await client.post(
            "/api/v1/complaints",
            json={
                "against_user_id": driver_user.id,
                "ride_id": 999999,
                "category": "other",
                "description": "Ride ID does not exist in the system at all.",
            },
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# API endpoint tests — GET /complaints/me/filed
# ---------------------------------------------------------------------------


class TestListMyFiledComplaints:
    @pytest.mark.asyncio
    async def test_returns_only_filed_by_me(
        self, client, rider, driver_user, rider_token, admin_token, db
    ):
        # Rider files a complaint
        await client.post(
            "/api/v1/complaints",
            json={
                "against_user_id": driver_user.id,
                "category": "fraud",
                "description": "Driver charged more than the quoted fare for the trip.",
            },
            headers={"Authorization": f"Bearer {rider_token}"},
        )

        resp = await client.get(
            "/api/v1/complaints/me/filed",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        for item in body:
            assert item["filed_by_user_id"] == rider.id

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_complaints(self, client, rider_token):
        resp = await client.get(
            "/api/v1/complaints/me/filed",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_pagination_limit_param(self, client, rider_token):
        resp = await client.get(
            "/api/v1/complaints/me/filed?limit=5&skip=0",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ---------------------------------------------------------------------------
# API endpoint tests — GET /complaints/me/received
# ---------------------------------------------------------------------------


class TestListComplaintsAgainstMe:
    @pytest.mark.asyncio
    async def test_returns_complaints_against_me(
        self, client, rider, driver_user, rider_token, driver_token
    ):
        # Driver files against rider
        await client.post(
            "/api/v1/complaints",
            json={
                "against_user_id": rider.id,
                "category": "inappropriate_behavior",
                "description": "Rider was extremely rude and left a mess in my vehicle.",
            },
            headers={"Authorization": f"Bearer {driver_token}"},
        )

        resp = await client.get(
            "/api/v1/complaints/me/received",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        for item in body:
            assert item["against_user_id"] == rider.id

    @pytest.mark.asyncio
    async def test_admin_notes_hidden_before_resolution(
        self, client, rider, driver_user, rider_token, driver_token, admin_token
    ):
        # Driver files against rider
        create_resp = await client.post(
            "/api/v1/complaints",
            json={
                "against_user_id": rider.id,
                "category": "inappropriate_behavior",
                "description": "Rider behaviour was inappropriate and uncomfortable for me.",
            },
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        complaint_id = create_resp.json()["id"]

        # Admin sets to reviewing (with notes)
        await client.put(
            f"/api/v1/admin/complaints/{complaint_id}",
            json={"status": "reviewing", "admin_notes": "Under investigation by safety team"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        # Rider (subject of complaint) should NOT see admin_notes yet
        resp = await client.get(
            "/api/v1/complaints/me/received",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 200
        for item in resp.json():
            if item["id"] == complaint_id:
                assert item["admin_notes"] is None

    @pytest.mark.asyncio
    async def test_admin_notes_visible_after_resolution(
        self, client, rider, driver_user, rider_token, driver_token, admin_token
    ):
        # Driver files against rider
        create_resp = await client.post(
            "/api/v1/complaints",
            json={
                "against_user_id": rider.id,
                "category": "inappropriate_behavior",
                "description": "Rider left garbage in the vehicle and was disrespectful.",
            },
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        complaint_id = create_resp.json()["id"]

        # Admin resolves with notes
        await client.put(
            f"/api/v1/admin/complaints/{complaint_id}",
            json={"status": "resolved", "admin_notes": "Complaint was substantiated."},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        # Rider (subject) should now see admin_notes
        resp = await client.get(
            "/api/v1/complaints/me/received",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 200
        found = next((c for c in resp.json() if c["id"] == complaint_id), None)
        assert found is not None
        assert found["admin_notes"] == "Complaint was substantiated."


# ---------------------------------------------------------------------------
# API endpoint tests — GET /admin/complaints
# ---------------------------------------------------------------------------


class TestAdminListComplaints:
    @pytest.mark.asyncio
    async def test_returns_all_complaints(
        self, client, rider, driver_user, rider_token, admin_token
    ):
        # File one complaint
        await client.post(
            "/api/v1/complaints",
            json={
                "against_user_id": driver_user.id,
                "category": "no_show",
                "description": "Driver never arrived at the pickup location despite being marked as arrived.",
            },
            headers={"Authorization": f"Bearer {rider_token}"},
        )

        resp = await client.get(
            "/api/v1/admin/complaints",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_status_filter_pending(self, client, admin_token):
        resp = await client.get(
            "/api/v1/admin/complaints?status=pending",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        for item in resp.json():
            assert item["status"] == "pending"

    @pytest.mark.asyncio
    async def test_status_filter_reviewing(self, client, admin_token):
        resp = await client.get(
            "/api/v1/admin/complaints?status=reviewing",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        for item in resp.json():
            assert item["status"] == "reviewing"

    @pytest.mark.asyncio
    async def test_status_filter_resolved(self, client, admin_token):
        resp = await client.get(
            "/api/v1/admin/complaints?status=resolved",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        for item in resp.json():
            assert item["status"] == "resolved"

    @pytest.mark.asyncio
    async def test_status_filter_dismissed(self, client, admin_token):
        resp = await client.get(
            "/api/v1/admin/complaints?status=dismissed",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        for item in resp.json():
            assert item["status"] == "dismissed"

    @pytest.mark.asyncio
    async def test_non_admin_is_rejected(self, client, rider_token):
        resp = await client.get(
            "/api/v1/admin/complaints",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_response_includes_user_names(
        self, client, rider, driver_user, rider_token, admin_token
    ):
        await client.post(
            "/api/v1/complaints",
            json={
                "against_user_id": driver_user.id,
                "category": "wrong_route",
                "description": "Driver took a significantly longer route than necessary on purpose.",
            },
            headers={"Authorization": f"Bearer {rider_token}"},
        )

        resp = await client.get(
            "/api/v1/admin/complaints",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) >= 1
        # AdminComplaintResponse includes filed_by_name and against_name
        assert "filed_by_name" in body[0]
        assert "against_name" in body[0]


# ---------------------------------------------------------------------------
# API endpoint tests — GET /admin/complaints/{id}
# ---------------------------------------------------------------------------


class TestAdminGetSingleComplaint:
    @pytest.mark.asyncio
    async def test_returns_complaint_details(
        self, client, rider, driver_user, rider_token, admin_token
    ):
        create_resp = await client.post(
            "/api/v1/complaints",
            json={
                "against_user_id": driver_user.id,
                "category": "discrimination",
                "description": "Driver refused service based on my appearance in a discriminatory way.",
            },
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        complaint_id = create_resp.json()["id"]

        resp = await client.get(
            f"/api/v1/admin/complaints/{complaint_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == complaint_id
        assert "filed_by_name" in body
        assert "against_name" in body

    @pytest.mark.asyncio
    async def test_returns_404_for_nonexistent(self, client, admin_token):
        resp = await client.get(
            "/api/v1/admin/complaints/999999",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# API endpoint tests — PUT /admin/complaints/{id}
# ---------------------------------------------------------------------------


class TestAdminUpdateComplaintEndpoint:
    @pytest.mark.asyncio
    async def test_set_to_reviewing_without_notes(
        self, client, rider, driver_user, rider_token, admin_token
    ):
        create_resp = await client.post(
            "/api/v1/complaints",
            json={
                "against_user_id": driver_user.id,
                "category": "vehicle_condition",
                "description": "The vehicle was filthy and had a broken seatbelt in the back seat.",
            },
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        complaint_id = create_resp.json()["id"]

        resp = await client.put(
            f"/api/v1/admin/complaints/{complaint_id}",
            json={"status": "reviewing"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "reviewing"

    @pytest.mark.asyncio
    async def test_resolve_complaint_with_notes(
        self, client, rider, driver_user, rider_token, admin_token
    ):
        create_resp = await client.post(
            "/api/v1/complaints",
            json={
                "against_user_id": driver_user.id,
                "category": "fraud",
                "description": "Driver claimed a cash payment was made that was never paid.",
            },
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        complaint_id = create_resp.json()["id"]

        resp = await client.put(
            f"/api/v1/admin/complaints/{complaint_id}",
            json={"status": "resolved", "admin_notes": "Verified via payment records. Action taken."},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "resolved"
        assert body["admin_notes"] == "Verified via payment records. Action taken."
        assert body["resolved_by_admin_id"] is not None

    @pytest.mark.asyncio
    async def test_dismiss_complaint_with_notes(
        self, client, rider, driver_user, rider_token, admin_token
    ):
        create_resp = await client.post(
            "/api/v1/complaints",
            json={
                "against_user_id": driver_user.id,
                "category": "harassment",
                "description": "Complaint filed with insufficient information or context provided.",
            },
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        complaint_id = create_resp.json()["id"]

        resp = await client.put(
            f"/api/v1/admin/complaints/{complaint_id}",
            json={"status": "dismissed", "admin_notes": "Insufficient evidence to substantiate claim."},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "dismissed"
        assert body["resolved_by_admin_id"] is not None

    @pytest.mark.asyncio
    async def test_cannot_re_resolve_already_resolved(
        self, client, rider, driver_user, rider_token, admin_token
    ):
        create_resp = await client.post(
            "/api/v1/complaints",
            json={
                "against_user_id": driver_user.id,
                "category": "other",
                "description": "General complaint to test the re-resolution protection logic here.",
            },
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        complaint_id = create_resp.json()["id"]

        # Resolve first time
        await client.put(
            f"/api/v1/admin/complaints/{complaint_id}",
            json={"status": "resolved", "admin_notes": "First resolution."},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        # Try to update again
        resp = await client.put(
            f"/api/v1/admin/complaints/{complaint_id}",
            json={"status": "dismissed", "admin_notes": "Trying to change decision."},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_non_admin_cannot_update_complaint(
        self, client, rider, driver_user, rider_token
    ):
        create_resp = await client.post(
            "/api/v1/complaints",
            json={
                "against_user_id": driver_user.id,
                "category": "other",
                "description": "Complaint filed to test access control on the admin update endpoint.",
            },
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        complaint_id = create_resp.json()["id"]

        resp = await client.put(
            f"/api/v1/admin/complaints/{complaint_id}",
            json={"status": "reviewing"},
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_notes_visible_after_resolve_on_filed_list(
        self, client, rider, driver_user, rider_token, admin_token
    ):
        """Resolved admin_notes appear in the filing user's complaint list."""
        create_resp = await client.post(
            "/api/v1/complaints",
            json={
                "against_user_id": driver_user.id,
                "category": "unsafe_driving",
                "description": "Driver was texting while driving at high speed on the highway.",
            },
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        complaint_id = create_resp.json()["id"]

        await client.put(
            f"/api/v1/admin/complaints/{complaint_id}",
            json={"status": "resolved", "admin_notes": "Driver received warning."},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        # Filing user should see notes after resolution
        resp = await client.get(
            "/api/v1/complaints/me/filed",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 200
        found = next((c for c in resp.json() if c["id"] == complaint_id), None)
        assert found is not None
        assert found["admin_notes"] == "Driver received warning."
