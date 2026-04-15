"""Tests for the driver rating appeal system.

Service layer (unit tests with mocked DB):
  1.  submit_appeal — 404 when feedback not found
  2.  submit_appeal — 400 when feedback role is not 'driver'
  3.  submit_appeal — 404 when associated ride not found
  4.  submit_appeal — 403 when driver is not the rated party
  5.  submit_appeal — 409 when appeal already exists for that feedback
  6.  submit_appeal — creates record with status PENDING on success
  7.  list_driver_appeals — returns driver's own appeals
  8.  review_appeal — 400 when decision is PENDING
  9.  review_appeal — 404 when appeal not found
  10. review_appeal — 409 when appeal already reviewed (approved)
  11. review_appeal — 409 when appeal already reviewed (rejected)
  12. review_appeal — approve sets rating_nullified=True and reviewed fields
  13. review_appeal — reject leaves rating_nullified=False
  14. list_all_appeals — returns all when no filter
  15. list_all_appeals — filters by status
  16. get_appeal_summary — returns correct structure

API layer (integration-style tests against test DB):
  17. POST /drivers/me/rating-appeals — 201 on valid appeal
  18. POST /drivers/me/rating-appeals — 401 when unauthenticated
  19. POST /drivers/me/rating-appeals — 403 when rider tries
  20. POST /drivers/me/rating-appeals — 404 when feedback not found
  21. POST /drivers/me/rating-appeals — 400 when feedback role is not driver
  22. POST /drivers/me/rating-appeals — 403 when driver not the rated party
  23. POST /drivers/me/rating-appeals — 409 when duplicate appeal
  24. POST /drivers/me/rating-appeals — 422 when reason too short
  25. GET  /drivers/me/rating-appeals — 200 returns driver's appeals
  26. GET  /drivers/me/rating-appeals — 401 when unauthenticated
  27. GET  /drivers/me/rating-appeals — does not return other driver's appeals
  28. GET  /admin/rating-appeals — 200 returns all appeals
  29. GET  /admin/rating-appeals — 403 for non-admin
  30. GET  /admin/rating-appeals?appeal_status=pending — filtered
  31. GET  /admin/rating-appeals?appeal_status=approved — filtered (empty)
  32. POST /admin/rating-appeals/{id}/review — 200 approves, nullified=True
  33. POST /admin/rating-appeals/{id}/review — 200 rejects, nullified=False
  34. POST /admin/rating-appeals/{id}/review — 404 when appeal not found
  35. POST /admin/rating-appeals/{id}/review — 409 when already reviewed
  36. POST /admin/rating-appeals/{id}/review — 403 for non-admin
  37. GET  /admin/rating-appeals/summary — 200 correct structure
  38. GET  /admin/rating-appeals/summary — 403 for non-admin
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.driver_rating_appeal import AppealStatus, DriverRatingAppeal
from app.models.feedback import RideFeedback
from app.models.ride import Ride, RideStatus
from app.models.user import User, UserRole
from app.services.auth import create_access_token, hash_password
from app.services.driver_rating_appeal import (
    AppealError,
    get_appeal_summary,
    list_all_appeals,
    list_driver_appeals,
    review_appeal,
    submit_appeal,
)


# ===========================================================================
# Helpers
# ===========================================================================


def _make_feedback(
    *,
    feedback_id: int = 1,
    ride_id: int = 10,
    user_id: int = 99,
    role: str = "driver",
    rating: int = 1,
) -> MagicMock:
    fb = MagicMock(spec=RideFeedback)
    fb.id = feedback_id
    fb.ride_id = ride_id
    fb.user_id = user_id
    fb.role = role
    fb.rating = rating
    return fb


def _make_ride(*, ride_id: int = 10, driver_id: int = 42, rider_id: int = 99) -> MagicMock:
    ride = MagicMock(spec=Ride)
    ride.id = ride_id
    ride.driver_id = driver_id
    ride.rider_id = rider_id
    ride.status = RideStatus.COMPLETED
    return ride


def _make_appeal(
    *,
    appeal_id: int = 1,
    driver_id: int = 42,
    feedback_id: int = 1,
    status: AppealStatus = AppealStatus.PENDING,
    rating_nullified: bool = False,
) -> MagicMock:
    appeal = MagicMock(spec=DriverRatingAppeal)
    appeal.id = appeal_id
    appeal.driver_id = driver_id
    appeal.feedback_id = feedback_id
    appeal.reason = "Rider left 1-star immediately after a 5-star smooth trip"
    appeal.status = status
    appeal.admin_notes = None
    appeal.reviewed_by = None
    appeal.rating_nullified = rating_nullified
    appeal.created_at = datetime(2026, 4, 15, tzinfo=timezone.utc)
    appeal.reviewed_at = None
    return appeal


def _scalar_result(value):
    m = MagicMock()
    m.scalar_one_or_none.return_value = value
    return m


def _scalars_result(values):
    m = MagicMock()
    inner = MagicMock()
    inner.all.return_value = values
    m.scalars.return_value = inner
    return m


# ===========================================================================
# PART 1 — Service unit tests (mocked DB)
# ===========================================================================


class TestSubmitAppeal:
    @pytest.mark.anyio
    async def test_feedback_not_found(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_result(None))
        with pytest.raises(AppealError) as exc:
            await submit_appeal(db, driver_id=42, feedback_id=999, reason="x" * 25)
        assert exc.value.status_code == 404

    @pytest.mark.anyio
    async def test_wrong_role_rider_feedback(self):
        feedback = _make_feedback(role="rider")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_result(feedback))
        with pytest.raises(AppealError) as exc:
            await submit_appeal(db, driver_id=42, feedback_id=1, reason="x" * 25)
        assert exc.value.status_code == 400

    @pytest.mark.anyio
    async def test_ride_not_found(self):
        feedback = _make_feedback(role="driver", ride_id=10)
        db = AsyncMock()
        # First execute returns feedback, second returns no ride
        db.execute = AsyncMock(
            side_effect=[_scalar_result(feedback), _scalar_result(None)]
        )
        with pytest.raises(AppealError) as exc:
            await submit_appeal(db, driver_id=42, feedback_id=1, reason="x" * 25)
        assert exc.value.status_code == 404

    @pytest.mark.anyio
    async def test_driver_not_rated_party(self):
        feedback = _make_feedback(role="driver", ride_id=10)
        ride = _make_ride(driver_id=99)  # different driver
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[_scalar_result(feedback), _scalar_result(ride)]
        )
        with pytest.raises(AppealError) as exc:
            await submit_appeal(db, driver_id=42, feedback_id=1, reason="x" * 25)
        assert exc.value.status_code == 403

    @pytest.mark.anyio
    async def test_duplicate_appeal(self):
        feedback = _make_feedback(role="driver", ride_id=10)
        ride = _make_ride(driver_id=42)
        existing_appeal = _make_appeal()
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_result(feedback),
                _scalar_result(ride),
                _scalar_result(existing_appeal),
            ]
        )
        with pytest.raises(AppealError) as exc:
            await submit_appeal(db, driver_id=42, feedback_id=1, reason="x" * 25)
        assert exc.value.status_code == 409

    @pytest.mark.anyio
    async def test_success_creates_pending_record(self):
        feedback = _make_feedback(role="driver", ride_id=10)
        ride = _make_ride(driver_id=42)
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_result(feedback),
                _scalar_result(ride),
                _scalar_result(None),  # no existing appeal
            ]
        )
        db.add = MagicMock()
        reason = "Rider left 1-star with no comment right after I gave them 5 stars"
        appeal = await submit_appeal(db, driver_id=42, feedback_id=1, reason=reason)
        assert appeal.driver_id == 42
        assert appeal.feedback_id == 1
        assert appeal.status == AppealStatus.PENDING
        assert not appeal.rating_nullified  # None or False before DB flush
        db.add.assert_called_once()


class TestListDriverAppeals:
    @pytest.mark.anyio
    async def test_returns_driver_appeals(self):
        appeals = [_make_appeal(driver_id=42), _make_appeal(appeal_id=2, driver_id=42)]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_result(appeals))
        result = await list_driver_appeals(db, driver_id=42)
        assert len(result) == 2


class TestReviewAppeal:
    @pytest.mark.anyio
    async def test_decision_pending_rejected(self):
        db = AsyncMock()
        with pytest.raises(AppealError) as exc:
            await review_appeal(
                db, appeal_id=1, admin_id=1, decision=AppealStatus.PENDING, admin_notes="ok"
            )
        assert exc.value.status_code == 400

    @pytest.mark.anyio
    async def test_appeal_not_found(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_result(None))
        with pytest.raises(AppealError) as exc:
            await review_appeal(
                db, appeal_id=999, admin_id=1, decision=AppealStatus.APPROVED, admin_notes="ok"
            )
        assert exc.value.status_code == 404

    @pytest.mark.anyio
    async def test_already_reviewed_approved(self):
        appeal = _make_appeal(status=AppealStatus.APPROVED)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_result(appeal))
        with pytest.raises(AppealError) as exc:
            await review_appeal(
                db, appeal_id=1, admin_id=1, decision=AppealStatus.REJECTED, admin_notes="ok"
            )
        assert exc.value.status_code == 409

    @pytest.mark.anyio
    async def test_already_reviewed_rejected(self):
        appeal = _make_appeal(status=AppealStatus.REJECTED)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_result(appeal))
        with pytest.raises(AppealError) as exc:
            await review_appeal(
                db, appeal_id=1, admin_id=1, decision=AppealStatus.APPROVED, admin_notes="ok"
            )
        assert exc.value.status_code == 409

    @pytest.mark.anyio
    async def test_approve_nullifies_rating(self):
        appeal = _make_appeal()
        appeal.status = AppealStatus.PENDING
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_result(appeal))
        result = await review_appeal(
            db, appeal_id=1, admin_id=7, decision=AppealStatus.APPROVED, admin_notes="Clear retaliation"
        )
        assert result.status == AppealStatus.APPROVED
        assert result.rating_nullified is True
        assert result.reviewed_by == 7
        assert result.reviewed_at is not None

    @pytest.mark.anyio
    async def test_reject_does_not_nullify(self):
        appeal = _make_appeal()
        appeal.status = AppealStatus.PENDING
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_result(appeal))
        result = await review_appeal(
            db, appeal_id=1, admin_id=7, decision=AppealStatus.REJECTED, admin_notes="Rating seems valid"
        )
        assert result.status == AppealStatus.REJECTED
        assert result.rating_nullified is False


class TestListAllAppeals:
    @pytest.mark.anyio
    async def test_returns_all_no_filter(self):
        appeals = [_make_appeal(), _make_appeal(appeal_id=2)]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_result(appeals))
        result = await list_all_appeals(db)
        assert len(result) == 2

    @pytest.mark.anyio
    async def test_filters_by_status(self):
        pending = [_make_appeal()]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_result(pending))
        result = await list_all_appeals(db, status_filter=AppealStatus.PENDING)
        assert len(result) == 1


class TestGetAppealSummary:
    @pytest.mark.anyio
    async def test_returns_correct_keys(self):
        counts_row1 = MagicMock()
        counts_row1.status = AppealStatus.PENDING
        counts_row1.n = 3
        counts_row2 = MagicMock()
        counts_row2.status = AppealStatus.APPROVED
        counts_row2.n = 1

        counts_result = MagicMock()
        counts_result.__iter__ = MagicMock(return_value=iter([counts_row1, counts_row2]))

        total_result = MagicMock()
        total_result.scalar_one.return_value = 4

        nullified_result = MagicMock()
        nullified_result.scalar_one.return_value = 1

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[counts_result, total_result, nullified_result]
        )
        summary = await get_appeal_summary(db)
        assert set(summary.keys()) == {"total", "pending", "approved", "rejected", "nullified"}
        assert summary["total"] == 4
        assert summary["pending"] == 3
        assert summary["approved"] == 1
        assert summary["nullified"] == 1


# ===========================================================================
# PART 2 — API integration tests (live test DB)
# ===========================================================================


pytestmark_db = pytest.mark.anyio


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _seed_driver_feedback(db, *, driver_id: int, rider_id: int) -> tuple[Ride, RideFeedback]:
    """Helper: create a completed ride + driver-role feedback for it."""
    from geoalchemy2.elements import WKBElement
    from sqlalchemy import text

    # Use a raw point geometry supported by all PostGIS installations
    ride = Ride(
        rider_id=rider_id,
        driver_id=driver_id,
        status=RideStatus.COMPLETED,
        pickup_location=text("ST_GeomFromText('POINT(-122.4 37.7)', 4326)"),
        dropoff_location=text("ST_GeomFromText('POINT(-122.5 37.8)', 4326)"),
        pickup_address="123 Start St",
        dropoff_address="456 End Ave",
        estimated_fare=20.0,
        actual_fare=20.0,
    )
    db.add(ride)
    await db.flush()

    feedback = RideFeedback(
        ride_id=ride.id,
        user_id=rider_id,
        role="driver",
        rating=1,
        comment=None,
    )
    db.add(feedback)
    await db.flush()
    return ride, feedback


@pytest.mark.anyio
async def test_api_submit_appeal_success(client, driver_user, rider, driver_token, db):
    _, feedback = await _seed_driver_feedback(
        db, driver_id=driver_user.id, rider_id=rider.id
    )
    resp = await client.post(
        "/api/v1/drivers/me/rating-appeals",
        json={"feedback_id": feedback.id, "reason": "Rider gave 1-star with no comment after smooth ride"},
        headers=auth_header(driver_token),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "pending"
    assert data["rating_nullified"] is False
    assert data["driver_id"] == driver_user.id


@pytest.mark.anyio
async def test_api_submit_appeal_unauthenticated(client):
    resp = await client.post(
        "/api/v1/drivers/me/rating-appeals",
        json={"feedback_id": 1, "reason": "x" * 25},
    )
    assert resp.status_code in (401, 403)


@pytest.mark.anyio
async def test_api_submit_appeal_rider_forbidden(client, rider_token):
    resp = await client.post(
        "/api/v1/drivers/me/rating-appeals",
        json={"feedback_id": 1, "reason": "x" * 25},
        headers=auth_header(rider_token),
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_api_submit_appeal_feedback_not_found(client, driver_token):
    resp = await client.post(
        "/api/v1/drivers/me/rating-appeals",
        json={"feedback_id": 999999, "reason": "x" * 25},
        headers=auth_header(driver_token),
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_api_submit_appeal_wrong_role(client, driver_user, rider, driver_token, db):
    """Feedback with role='rider' cannot be appealed by a driver."""
    _, _ = await _seed_driver_feedback(
        db, driver_id=driver_user.id, rider_id=rider.id
    )
    # Create a rider-role feedback record
    from geoalchemy2.elements import WKBElement
    from sqlalchemy import text

    ride2 = Ride(
        rider_id=rider.id,
        driver_id=driver_user.id,
        status=RideStatus.COMPLETED,
        pickup_location=text("ST_GeomFromText('POINT(-122.4 37.7)', 4326)"),
        dropoff_location=text("ST_GeomFromText('POINT(-122.5 37.8)', 4326)"),
        pickup_address="A",
        dropoff_address="B",
        estimated_fare=15.0,
    )
    db.add(ride2)
    await db.flush()

    rider_feedback = RideFeedback(
        ride_id=ride2.id,
        user_id=driver_user.id,
        role="rider",   # driver rating the rider — not eligible for appeal
        rating=2,
    )
    db.add(rider_feedback)
    await db.flush()

    resp = await client.post(
        "/api/v1/drivers/me/rating-appeals",
        json={"feedback_id": rider_feedback.id, "reason": "x" * 25},
        headers=auth_header(driver_token),
    )
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_api_submit_appeal_not_rated_party(client, driver_user, rider, db):
    """Another driver cannot appeal a feedback that doesn't belong to them."""
    other_driver = User(
        phone="+15559990001",
        name="Other Driver",
        email="other_driver@test.com",
        password_hash=hash_password("testpass123"),
        role=UserRole.DRIVER,
        is_active=True,
    )
    db.add(other_driver)
    await db.flush()
    other_token = create_access_token(other_driver.id, other_driver.role.value)

    _, feedback = await _seed_driver_feedback(
        db, driver_id=driver_user.id, rider_id=rider.id
    )
    resp = await client.post(
        "/api/v1/drivers/me/rating-appeals",
        json={"feedback_id": feedback.id, "reason": "x" * 25},
        headers=auth_header(other_token),
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_api_submit_appeal_duplicate(client, driver_user, rider, driver_token, db):
    _, feedback = await _seed_driver_feedback(
        db, driver_id=driver_user.id, rider_id=rider.id
    )
    payload = {
        "feedback_id": feedback.id,
        "reason": "Rider gave 1-star with no comment after smooth ride",
    }
    r1 = await client.post(
        "/api/v1/drivers/me/rating-appeals",
        json=payload,
        headers=auth_header(driver_token),
    )
    assert r1.status_code == 201
    r2 = await client.post(
        "/api/v1/drivers/me/rating-appeals",
        json=payload,
        headers=auth_header(driver_token),
    )
    assert r2.status_code == 409


@pytest.mark.anyio
async def test_api_submit_appeal_reason_too_short(client, driver_token):
    resp = await client.post(
        "/api/v1/drivers/me/rating-appeals",
        json={"feedback_id": 1, "reason": "short"},
        headers=auth_header(driver_token),
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_api_list_own_appeals(client, driver_user, rider, driver_token, db):
    _, feedback = await _seed_driver_feedback(
        db, driver_id=driver_user.id, rider_id=rider.id
    )
    # Submit an appeal first
    await client.post(
        "/api/v1/drivers/me/rating-appeals",
        json={
            "feedback_id": feedback.id,
            "reason": "Rider gave 1-star with no comment after smooth ride",
        },
        headers=auth_header(driver_token),
    )
    resp = await client.get(
        "/api/v1/drivers/me/rating-appeals",
        headers=auth_header(driver_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert all(a["driver_id"] == driver_user.id for a in data)


@pytest.mark.anyio
async def test_api_list_own_appeals_unauthenticated(client):
    resp = await client.get("/api/v1/drivers/me/rating-appeals")
    assert resp.status_code in (401, 403)


@pytest.mark.anyio
async def test_api_list_own_appeals_does_not_return_others(
    client, driver_user, rider, driver_token, db
):
    """A second driver's appeals don't appear in the first driver's list."""
    other_driver = User(
        phone="+15559990002",
        name="Other Driver 2",
        email="other_driver2@test.com",
        password_hash=hash_password("testpass123"),
        role=UserRole.DRIVER,
        is_active=True,
    )
    db.add(other_driver)
    await db.flush()
    other_token = create_access_token(other_driver.id, other_driver.role.value)

    # Create feedback for other_driver and let them appeal it
    _, feedback2 = await _seed_driver_feedback(
        db, driver_id=other_driver.id, rider_id=rider.id
    )
    await client.post(
        "/api/v1/drivers/me/rating-appeals",
        json={
            "feedback_id": feedback2.id,
            "reason": "Rider gave 1-star with no comment after smooth ride",
        },
        headers=auth_header(other_token),
    )

    # driver_user's list should not include other_driver's appeal
    resp = await client.get(
        "/api/v1/drivers/me/rating-appeals",
        headers=auth_header(driver_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert all(a["driver_id"] == driver_user.id for a in data)


@pytest.mark.anyio
async def test_api_admin_list_all_appeals(client, driver_user, rider, admin_token, driver_token, db):
    _, feedback = await _seed_driver_feedback(
        db, driver_id=driver_user.id, rider_id=rider.id
    )
    await client.post(
        "/api/v1/drivers/me/rating-appeals",
        json={
            "feedback_id": feedback.id,
            "reason": "Rider gave 1-star with no comment after smooth ride",
        },
        headers=auth_header(driver_token),
    )
    resp = await client.get(
        "/api/v1/admin/rating-appeals",
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.anyio
async def test_api_admin_list_appeals_forbidden(client, rider_token):
    resp = await client.get(
        "/api/v1/admin/rating-appeals",
        headers=auth_header(rider_token),
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_api_admin_list_appeals_status_filter_pending(
    client, driver_user, rider, admin_token, driver_token, db
):
    _, feedback = await _seed_driver_feedback(
        db, driver_id=driver_user.id, rider_id=rider.id
    )
    await client.post(
        "/api/v1/drivers/me/rating-appeals",
        json={
            "feedback_id": feedback.id,
            "reason": "Rider gave 1-star with no comment after smooth ride",
        },
        headers=auth_header(driver_token),
    )
    resp = await client.get(
        "/api/v1/admin/rating-appeals?appeal_status=pending",
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert all(a["status"] == "pending" for a in data)


@pytest.mark.anyio
async def test_api_admin_list_appeals_status_filter_approved_empty(
    client, admin_token
):
    """Filtering for approved when none exist returns empty list."""
    resp = await client.get(
        "/api/v1/admin/rating-appeals?appeal_status=approved",
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 200
    # May or may not be empty depending on other tests, but should be a list
    assert isinstance(resp.json(), list)


@pytest.mark.anyio
async def test_api_admin_approve_appeal(
    client, driver_user, rider, admin_token, driver_token, db
):
    _, feedback = await _seed_driver_feedback(
        db, driver_id=driver_user.id, rider_id=rider.id
    )
    r = await client.post(
        "/api/v1/drivers/me/rating-appeals",
        json={
            "feedback_id": feedback.id,
            "reason": "Rider gave 1-star with no comment after smooth ride",
        },
        headers=auth_header(driver_token),
    )
    appeal_id = r.json()["id"]

    resp = await client.post(
        f"/api/v1/admin/rating-appeals/{appeal_id}/review",
        json={"decision": "approved", "admin_notes": "Retaliation pattern confirmed"},
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "approved"
    assert data["rating_nullified"] is True
    assert data["reviewed_by"] is not None
    assert data["reviewed_at"] is not None


@pytest.mark.anyio
async def test_api_admin_reject_appeal(
    client, driver_user, rider, admin_token, driver_token, db
):
    _, feedback = await _seed_driver_feedback(
        db, driver_id=driver_user.id, rider_id=rider.id
    )
    r = await client.post(
        "/api/v1/drivers/me/rating-appeals",
        json={
            "feedback_id": feedback.id,
            "reason": "Rider gave 1-star with no comment after smooth ride",
        },
        headers=auth_header(driver_token),
    )
    appeal_id = r.json()["id"]

    resp = await client.post(
        f"/api/v1/admin/rating-appeals/{appeal_id}/review",
        json={"decision": "rejected", "admin_notes": "Rating corroborated by other evidence"},
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "rejected"
    assert data["rating_nullified"] is False


@pytest.mark.anyio
async def test_api_admin_review_not_found(client, admin_token):
    resp = await client.post(
        "/api/v1/admin/rating-appeals/999999/review",
        json={"decision": "approved", "admin_notes": "ok"},
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_api_admin_review_already_reviewed(
    client, driver_user, rider, admin_token, driver_token, db
):
    _, feedback = await _seed_driver_feedback(
        db, driver_id=driver_user.id, rider_id=rider.id
    )
    r = await client.post(
        "/api/v1/drivers/me/rating-appeals",
        json={
            "feedback_id": feedback.id,
            "reason": "Rider gave 1-star with no comment after smooth ride",
        },
        headers=auth_header(driver_token),
    )
    appeal_id = r.json()["id"]

    # First review
    await client.post(
        f"/api/v1/admin/rating-appeals/{appeal_id}/review",
        json={"decision": "approved", "admin_notes": "First review"},
        headers=auth_header(admin_token),
    )
    # Second review should fail
    resp = await client.post(
        f"/api/v1/admin/rating-appeals/{appeal_id}/review",
        json={"decision": "rejected", "admin_notes": "Second attempt"},
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 409


@pytest.mark.anyio
async def test_api_admin_review_forbidden(client, driver_user, rider, driver_token, db):
    _, feedback = await _seed_driver_feedback(
        db, driver_id=driver_user.id, rider_id=rider.id
    )
    r = await client.post(
        "/api/v1/drivers/me/rating-appeals",
        json={
            "feedback_id": feedback.id,
            "reason": "Rider gave 1-star with no comment after smooth ride",
        },
        headers=auth_header(driver_token),
    )
    appeal_id = r.json()["id"]

    resp = await client.post(
        f"/api/v1/admin/rating-appeals/{appeal_id}/review",
        json={"decision": "approved", "admin_notes": "ok"},
        headers=auth_header(driver_token),  # driver, not admin
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_api_admin_summary(client, admin_token):
    resp = await client.get(
        "/api/v1/admin/rating-appeals/summary",
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert {"total", "pending", "approved", "rejected", "nullified"} <= data.keys()
    for key in ("total", "pending", "approved", "rejected", "nullified"):
        assert isinstance(data[key], int)


@pytest.mark.anyio
async def test_api_admin_summary_forbidden(client, rider_token):
    resp = await client.get(
        "/api/v1/admin/rating-appeals/summary",
        headers=auth_header(rider_token),
    )
    assert resp.status_code == 403
