"""Tests for the Corporate Batch/Group Booking feature.

Service tests (async, mocked DB):
  1.  create_batch — success (admin)
  2.  create_batch — not admin → 403
  3.  get_batch — success (member)
  4.  get_batch — not member → 403
  5.  get_batch — wrong account → 404
  6.  list_batches — success, no filter (member)
  7.  list_batches — success with status filter
  8.  list_batches — not member → 403
  9.  update_batch — success (admin, draft only)
  10. update_batch — not draft → 400
  11. update_batch — not admin → 403
  12. add_ride_request — success
  13. add_ride_request — batch not draft → 400
  14. add_ride_request — capacity reached (50) → 400
  15. add_ride_request — not admin → 403
  16. remove_ride_request — success
  17. remove_ride_request — already removed → 404
  18. remove_ride_request — not admin → 403
  19. submit_batch — success
  20. submit_batch — no pending requests → 400
  21. submit_batch — not draft → 400
  22. submit_batch — not admin → 403
  23. cancel_batch — success (draft)
  24. cancel_batch — already cancelled → 400
  25. cancel_batch — not admin → 403
  26. get_batch_with_requests — success (member)
  27. get_batch_with_requests — not member → 403

Schema tests (sync):
  28. BatchBookingCreate — valid
  29. BatchBookingCreate — name too long → ValidationError
  30. BatchRideRequestCreate — valid
  31. BatchBookingResponse — serialises ride_request_count
  32. BatchRideRequestListResponse — pending/removed counts

API layer tests (asyncio, service patched):
  33. POST /corporate/accounts/me/batches — 201
  34. GET /corporate/accounts/me/batches — 200
  35. GET /corporate/accounts/me/batches/{id} — 200
  36. POST /corporate/accounts/me/batches/{id}/submit — 200
  37. DELETE /corporate/accounts/me/batches/{id} — 200 with reason
  38. GET /admin/corporate/accounts/{id}/batches — 200 admin path
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.corporate import BusinessAccountMember, MemberRole
from app.models.corporate_batch_booking import (
    BatchBookingStatus,
    BatchRideRequestStatus,
    CorporateBatchBooking,
    CorporateBatchRideRequest,
)
from app.schemas.corporate_batch_booking import (
    BatchBookingCreate,
    BatchBookingResponse,
    BatchBookingUpdate,
    BatchRideRequestCreate,
    BatchRideRequestListResponse,
    BatchRideRequestResponse,
    BatchBookingSummary,
    CancelBatchRequest,
)
from app.services.corporate_batch_booking import (
    add_ride_request,
    cancel_batch,
    create_batch,
    get_batch,
    get_batch_with_requests,
    list_batches,
    remove_ride_request,
    submit_batch,
    update_batch,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
EVENT_DATE = date(2026, 6, 1)
ACCOUNT_ID = 10
USER_ID = 1
ADMIN_ID = 2
BATCH_ID = 42
REQUEST_ID = 7


def _make_member(
    account_id: int = ACCOUNT_ID,
    user_id: int = USER_ID,
    role: MemberRole = MemberRole.MEMBER,
    is_active: bool = True,
) -> MagicMock:
    m = MagicMock(spec=BusinessAccountMember)
    m.account_id = account_id
    m.user_id = user_id
    m.role = role
    m.is_active = is_active
    return m


def _make_admin_member(
    account_id: int = ACCOUNT_ID, user_id: int = ADMIN_ID
) -> MagicMock:
    return _make_member(account_id=account_id, user_id=user_id, role=MemberRole.ADMIN)


def _scalar_result(value) -> MagicMock:
    res = MagicMock()
    res.scalar_one_or_none.return_value = value
    res.scalar.return_value = value
    return res


def _all_result(rows: list) -> MagicMock:
    res = MagicMock()
    res.all.return_value = rows
    res.scalars.return_value.all.return_value = rows
    return res


def _make_batch(
    batch_id: int = BATCH_ID,
    account_id: int = ACCOUNT_ID,
    name: str = "Test Batch",
    status: BatchBookingStatus = BatchBookingStatus.DRAFT,
) -> MagicMock:
    b = MagicMock(spec=CorporateBatchBooking)
    b.id = batch_id
    b.account_id = account_id
    b.name = name
    b.event_date = EVENT_DATE
    b.notes = None
    b.status = status
    b.created_by_user_id = ADMIN_ID
    b.submitted_at = None
    b.cancelled_at = None
    b.cancellation_reason = None
    b.created_at = NOW
    b.updated_at = NOW
    return b


def _make_ride_request(
    request_id: int = REQUEST_ID,
    batch_id: int = BATCH_ID,
    account_id: int = ACCOUNT_ID,
    status: BatchRideRequestStatus = BatchRideRequestStatus.PENDING,
) -> MagicMock:
    r = MagicMock(spec=CorporateBatchRideRequest)
    r.id = request_id
    r.batch_id = batch_id
    r.account_id = account_id
    r.passenger_name = "Alice Smith"
    r.passenger_email = "alice@corp.com"
    r.passenger_phone = "+15551234567"
    r.pickup_address = "123 Main St"
    r.pickup_lat = Decimal("37.774929")
    r.pickup_lng = Decimal("-122.419416")
    r.dropoff_address = "456 Market St"
    r.dropoff_lat = Decimal("37.791460")
    r.dropoff_lng = Decimal("-122.396780")
    r.requested_time = NOW
    r.notes = None
    r.status = status
    r.added_at = NOW
    return r


def _valid_ride_request_data() -> BatchRideRequestCreate:
    return BatchRideRequestCreate(
        passenger_name="Alice Smith",
        passenger_email="alice@corp.com",
        passenger_phone="+15551234567",
        pickup_address="123 Main St",
        dropoff_address="456 Market St",
        requested_time=NOW,
    )


# ---------------------------------------------------------------------------
# 1. create_batch — success (admin)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_batch_success():
    db = AsyncMock()
    admin = _make_admin_member()
    batch = _make_batch()

    db.execute.return_value = _scalar_result(admin)
    db.add = MagicMock()
    db.flush = AsyncMock()

    data = BatchBookingCreate(name="Q2 Offsite Shuttles", event_date=EVENT_DATE)

    # Patch the ORM class construction to return our mock
    with patch(
        "app.services.corporate_batch_booking.CorporateBatchBooking",
        return_value=batch,
    ):
        result = await create_batch(db, ACCOUNT_ID, requesting_user_id=ADMIN_ID, data=data)

    db.add.assert_called_once_with(batch)
    db.flush.assert_awaited_once()
    assert result is batch


# ---------------------------------------------------------------------------
# 2. create_batch — not admin → 403
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_batch_not_admin():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)  # admin check fails

    data = BatchBookingCreate(name="Q2 Offsite Shuttles")

    with pytest.raises(HTTPException) as exc_info:
        await create_batch(db, ACCOUNT_ID, requesting_user_id=USER_ID, data=data)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 3. get_batch — success (member)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_batch_success():
    db = AsyncMock()
    member = _make_member()
    batch = _make_batch()

    db.execute.side_effect = [
        _scalar_result(member),   # _require_account_member
        _scalar_result(batch),    # _get_batch_or_404
    ]

    result = await get_batch(db, ACCOUNT_ID, BATCH_ID, requesting_user_id=USER_ID)
    assert result is batch


# ---------------------------------------------------------------------------
# 4. get_batch — not member → 403
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_batch_not_member():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc_info:
        await get_batch(db, ACCOUNT_ID, BATCH_ID, requesting_user_id=99)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 5. get_batch — wrong account → 404
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_batch_wrong_account():
    db = AsyncMock()
    member = _make_member()

    db.execute.side_effect = [
        _scalar_result(member),   # member check passes
        _scalar_result(None),     # batch not found for this account
    ]

    with pytest.raises(HTTPException) as exc_info:
        await get_batch(db, ACCOUNT_ID, BATCH_ID, requesting_user_id=USER_ID)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 6. list_batches — success, no filter (member)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_batches_success_no_filter():
    db = AsyncMock()
    member = _make_member()
    batches = [_make_batch(batch_id=1), _make_batch(batch_id=2)]

    db.execute.side_effect = [
        _scalar_result(member),
        _all_result(batches),
    ]

    result = await list_batches(db, ACCOUNT_ID, requesting_user_id=USER_ID)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# 7. list_batches — success with status filter
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_batches_with_status_filter():
    db = AsyncMock()
    member = _make_member()
    submitted_batch = _make_batch(status=BatchBookingStatus.SUBMITTED)

    db.execute.side_effect = [
        _scalar_result(member),
        _all_result([submitted_batch]),
    ]

    result = await list_batches(
        db, ACCOUNT_ID, requesting_user_id=USER_ID, status_filter=BatchBookingStatus.SUBMITTED
    )
    assert len(result) == 1
    assert result[0].status == BatchBookingStatus.SUBMITTED


# ---------------------------------------------------------------------------
# 8. list_batches — not member → 403
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_batches_not_member():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc_info:
        await list_batches(db, ACCOUNT_ID, requesting_user_id=99)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 9. update_batch — success (admin, draft only)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_batch_success():
    db = AsyncMock()
    admin = _make_admin_member()
    batch = _make_batch()

    db.execute.side_effect = [
        _scalar_result(admin),
        _scalar_result(batch),
    ]
    db.flush = AsyncMock()

    data = BatchBookingUpdate(name="Updated Name")
    result = await update_batch(db, ACCOUNT_ID, BATCH_ID, requesting_user_id=ADMIN_ID, data=data)

    assert batch.name == "Updated Name"
    db.flush.assert_awaited_once()
    assert result is batch


# ---------------------------------------------------------------------------
# 10. update_batch — not draft → 400
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_batch_not_draft():
    db = AsyncMock()
    admin = _make_admin_member()
    submitted_batch = _make_batch(status=BatchBookingStatus.SUBMITTED)

    db.execute.side_effect = [
        _scalar_result(admin),
        _scalar_result(submitted_batch),
    ]

    data = BatchBookingUpdate(name="New Name")
    with pytest.raises(HTTPException) as exc_info:
        await update_batch(db, ACCOUNT_ID, BATCH_ID, requesting_user_id=ADMIN_ID, data=data)
    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# 11. update_batch — not admin → 403
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_batch_not_admin():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    data = BatchBookingUpdate(name="New Name")
    with pytest.raises(HTTPException) as exc_info:
        await update_batch(db, ACCOUNT_ID, BATCH_ID, requesting_user_id=USER_ID, data=data)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 12. add_ride_request — success
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_add_ride_request_success():
    db = AsyncMock()
    admin = _make_admin_member()
    batch = _make_batch()
    ride_request = _make_ride_request()

    db.execute.side_effect = [
        _scalar_result(admin),    # admin check
        _scalar_result(batch),    # get batch
        _scalar_result(5),        # count pending (< 50)
    ]
    db.add = MagicMock()
    db.flush = AsyncMock()

    data = _valid_ride_request_data()

    with patch(
        "app.services.corporate_batch_booking.CorporateBatchRideRequest",
        return_value=ride_request,
    ):
        result = await add_ride_request(
            db, ACCOUNT_ID, BATCH_ID, requesting_user_id=ADMIN_ID, data=data
        )

    db.add.assert_called_once_with(ride_request)
    db.flush.assert_awaited_once()
    assert result is ride_request


# ---------------------------------------------------------------------------
# 13. add_ride_request — batch not draft → 400
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_add_ride_request_batch_not_draft():
    db = AsyncMock()
    admin = _make_admin_member()
    submitted_batch = _make_batch(status=BatchBookingStatus.SUBMITTED)

    db.execute.side_effect = [
        _scalar_result(admin),
        _scalar_result(submitted_batch),
    ]

    data = _valid_ride_request_data()
    with pytest.raises(HTTPException) as exc_info:
        await add_ride_request(
            db, ACCOUNT_ID, BATCH_ID, requesting_user_id=ADMIN_ID, data=data
        )
    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# 14. add_ride_request — capacity reached (50) → 400
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_add_ride_request_capacity_reached():
    db = AsyncMock()
    admin = _make_admin_member()
    batch = _make_batch()

    db.execute.side_effect = [
        _scalar_result(admin),
        _scalar_result(batch),
        _scalar_result(50),    # already at capacity
    ]

    data = _valid_ride_request_data()
    with pytest.raises(HTTPException) as exc_info:
        await add_ride_request(
            db, ACCOUNT_ID, BATCH_ID, requesting_user_id=ADMIN_ID, data=data
        )
    assert exc_info.value.status_code == 400
    assert "capacity" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# 15. add_ride_request — not admin → 403
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_add_ride_request_not_admin():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    data = _valid_ride_request_data()
    with pytest.raises(HTTPException) as exc_info:
        await add_ride_request(
            db, ACCOUNT_ID, BATCH_ID, requesting_user_id=USER_ID, data=data
        )
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 16. remove_ride_request — success
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_remove_ride_request_success():
    db = AsyncMock()
    admin = _make_admin_member()
    batch = _make_batch()
    ride_request = _make_ride_request(status=BatchRideRequestStatus.PENDING)

    db.execute.side_effect = [
        _scalar_result(admin),
        _scalar_result(batch),
        _scalar_result(ride_request),
    ]
    db.flush = AsyncMock()

    await remove_ride_request(
        db, ACCOUNT_ID, BATCH_ID, REQUEST_ID, requesting_user_id=ADMIN_ID
    )

    assert ride_request.status == BatchRideRequestStatus.REMOVED
    db.flush.assert_awaited_once()


# ---------------------------------------------------------------------------
# 17. remove_ride_request — already removed → 404
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_remove_ride_request_already_removed():
    db = AsyncMock()
    admin = _make_admin_member()
    batch = _make_batch()
    already_removed = _make_ride_request(status=BatchRideRequestStatus.REMOVED)

    db.execute.side_effect = [
        _scalar_result(admin),
        _scalar_result(batch),
        _scalar_result(already_removed),
    ]

    with pytest.raises(HTTPException) as exc_info:
        await remove_ride_request(
            db, ACCOUNT_ID, BATCH_ID, REQUEST_ID, requesting_user_id=ADMIN_ID
        )
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 18. remove_ride_request — not admin → 403
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_remove_ride_request_not_admin():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc_info:
        await remove_ride_request(
            db, ACCOUNT_ID, BATCH_ID, REQUEST_ID, requesting_user_id=USER_ID
        )
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 19. submit_batch — success
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_submit_batch_success():
    db = AsyncMock()
    admin = _make_admin_member()
    batch = _make_batch()

    db.execute.side_effect = [
        _scalar_result(admin),
        _scalar_result(batch),
        _scalar_result(3),    # 3 pending requests
    ]
    db.flush = AsyncMock()

    result = await submit_batch(db, ACCOUNT_ID, BATCH_ID, requesting_user_id=ADMIN_ID)

    assert batch.status == BatchBookingStatus.SUBMITTED
    assert batch.submitted_at is not None
    db.flush.assert_awaited_once()
    assert result is batch


# ---------------------------------------------------------------------------
# 20. submit_batch — no pending requests → 400
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_submit_batch_no_pending_requests():
    db = AsyncMock()
    admin = _make_admin_member()
    batch = _make_batch()

    db.execute.side_effect = [
        _scalar_result(admin),
        _scalar_result(batch),
        _scalar_result(0),    # no pending requests
    ]

    with pytest.raises(HTTPException) as exc_info:
        await submit_batch(db, ACCOUNT_ID, BATCH_ID, requesting_user_id=ADMIN_ID)
    assert exc_info.value.status_code == 400
    assert "no ride requests" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# 21. submit_batch — not draft → 400
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_submit_batch_not_draft():
    db = AsyncMock()
    admin = _make_admin_member()
    already_submitted = _make_batch(status=BatchBookingStatus.SUBMITTED)

    db.execute.side_effect = [
        _scalar_result(admin),
        _scalar_result(already_submitted),
    ]

    with pytest.raises(HTTPException) as exc_info:
        await submit_batch(db, ACCOUNT_ID, BATCH_ID, requesting_user_id=ADMIN_ID)
    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# 22. submit_batch — not admin → 403
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_submit_batch_not_admin():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc_info:
        await submit_batch(db, ACCOUNT_ID, BATCH_ID, requesting_user_id=USER_ID)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 23. cancel_batch — success (draft)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cancel_batch_success():
    db = AsyncMock()
    admin = _make_admin_member()
    batch = _make_batch()

    db.execute.side_effect = [
        _scalar_result(admin),
        _scalar_result(batch),
    ]
    db.flush = AsyncMock()

    result = await cancel_batch(
        db, ACCOUNT_ID, BATCH_ID, requesting_user_id=ADMIN_ID, reason="Event cancelled"
    )

    assert batch.status == BatchBookingStatus.CANCELLED
    assert batch.cancelled_at is not None
    assert batch.cancellation_reason == "Event cancelled"
    db.flush.assert_awaited_once()
    assert result is batch


# ---------------------------------------------------------------------------
# 24. cancel_batch — already cancelled → 400
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cancel_batch_already_cancelled():
    db = AsyncMock()
    admin = _make_admin_member()
    cancelled_batch = _make_batch(status=BatchBookingStatus.CANCELLED)

    db.execute.side_effect = [
        _scalar_result(admin),
        _scalar_result(cancelled_batch),
    ]

    with pytest.raises(HTTPException) as exc_info:
        await cancel_batch(db, ACCOUNT_ID, BATCH_ID, requesting_user_id=ADMIN_ID)
    assert exc_info.value.status_code == 400
    assert "already cancelled" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# 25. cancel_batch — not admin → 403
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cancel_batch_not_admin():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc_info:
        await cancel_batch(db, ACCOUNT_ID, BATCH_ID, requesting_user_id=USER_ID)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 26. get_batch_with_requests — success (member)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_batch_with_requests_success():
    db = AsyncMock()
    member = _make_member()
    batch = _make_batch()
    requests = [_make_ride_request(request_id=1), _make_ride_request(request_id=2)]

    db.execute.side_effect = [
        _scalar_result(member),
        _scalar_result(batch),
        _all_result(requests),
    ]

    result_batch, result_requests = await get_batch_with_requests(
        db, ACCOUNT_ID, BATCH_ID, requesting_user_id=USER_ID
    )

    assert result_batch is batch
    assert len(result_requests) == 2


# ---------------------------------------------------------------------------
# 27. get_batch_with_requests — not member → 403
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_batch_with_requests_not_member():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc_info:
        await get_batch_with_requests(db, ACCOUNT_ID, BATCH_ID, requesting_user_id=99)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_batch_booking_create_valid():
    """28. BatchBookingCreate — valid."""
    data = BatchBookingCreate(
        name="Q2 Sales Offsite Shuttles",
        event_date=EVENT_DATE,
        notes="Please confirm 24 hours before",
    )
    assert data.name == "Q2 Sales Offsite Shuttles"
    assert data.event_date == EVENT_DATE
    assert data.notes == "Please confirm 24 hours before"


def test_batch_booking_create_name_too_long():
    """29. BatchBookingCreate — name too long → ValidationError."""
    with pytest.raises(ValidationError):
        BatchBookingCreate(name="x" * 201)


def test_batch_ride_request_create_valid():
    """30. BatchRideRequestCreate — valid."""
    data = BatchRideRequestCreate(
        passenger_name="Bob Jones",
        passenger_email="bob@corp.com",
        passenger_phone="+15559876543",
        pickup_address="789 Oak Ave",
        pickup_lat=Decimal("37.774929"),
        pickup_lng=Decimal("-122.419416"),
        dropoff_address="321 Pine St",
        dropoff_lat=Decimal("37.791460"),
        dropoff_lng=Decimal("-122.396780"),
        requested_time=NOW,
        notes="Prefers front seat",
    )
    assert data.passenger_name == "Bob Jones"
    assert data.pickup_lat == Decimal("37.774929")


def test_batch_booking_response_serialises_ride_request_count():
    """31. BatchBookingResponse — serialises ride_request_count."""
    r = BatchBookingResponse(
        id=BATCH_ID,
        account_id=ACCOUNT_ID,
        name="Test Batch",
        event_date=EVENT_DATE,
        notes=None,
        status=BatchBookingStatus.DRAFT,
        created_by_user_id=ADMIN_ID,
        submitted_at=None,
        cancelled_at=None,
        cancellation_reason=None,
        created_at=NOW,
        updated_at=NOW,
        ride_request_count=12,
    )
    assert r.ride_request_count == 12
    assert r.status == BatchBookingStatus.DRAFT


def test_batch_ride_request_list_response_counts():
    """32. BatchRideRequestListResponse — pending/removed counts."""
    rr = BatchRideRequestResponse(
        id=REQUEST_ID,
        batch_id=BATCH_ID,
        account_id=ACCOUNT_ID,
        passenger_name="Alice Smith",
        passenger_email=None,
        passenger_phone=None,
        pickup_address="123 Main St",
        pickup_lat=None,
        pickup_lng=None,
        dropoff_address="456 Market St",
        dropoff_lat=None,
        dropoff_lng=None,
        requested_time=NOW,
        notes=None,
        status=BatchRideRequestStatus.PENDING,
        added_at=NOW,
    )
    resp = BatchRideRequestListResponse(
        batch_id=BATCH_ID,
        total_count=3,
        pending_count=2,
        removed_count=1,
        requests=[rr],
    )
    assert resp.pending_count == 2
    assert resp.removed_count == 1
    assert len(resp.requests) == 1


# ---------------------------------------------------------------------------
# API layer tests
# ---------------------------------------------------------------------------

_ROUTER = "app.api.v1.corporate_batch_booking"


def _mock_user(user_id: int = USER_ID) -> MagicMock:
    u = MagicMock()
    u.id = user_id
    return u


def _mock_batch_response() -> BatchBookingResponse:
    return BatchBookingResponse(
        id=BATCH_ID,
        account_id=ACCOUNT_ID,
        name="Test Batch",
        event_date=EVENT_DATE,
        notes=None,
        status=BatchBookingStatus.DRAFT,
        created_by_user_id=ADMIN_ID,
        submitted_at=None,
        cancelled_at=None,
        cancellation_reason=None,
        created_at=NOW,
        updated_at=NOW,
        ride_request_count=0,
    )


def _mock_batch_summary() -> BatchBookingSummary:
    return BatchBookingSummary(
        id=BATCH_ID,
        account_id=ACCOUNT_ID,
        name="Test Batch",
        event_date=EVENT_DATE,
        status=BatchBookingStatus.DRAFT,
        created_at=NOW,
        ride_request_count=0,
    )


def _mock_batch_orm() -> MagicMock:
    """Return a MagicMock ORM object that _batch_response/_batch_summary can use."""
    b = _make_batch()
    return b


@pytest.mark.asyncio
async def test_api_create_batch():
    """33. POST /corporate/accounts/me/batches — 201."""
    from app.api.v1.corporate_batch_booking import create_my_batch

    user = _mock_user(user_id=ADMIN_ID)
    db = AsyncMock()
    data = BatchBookingCreate(name="Q2 Offsite")
    batch_orm = _mock_batch_orm()

    with patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch(f"{_ROUTER}.create_batch", new=AsyncMock(return_value=batch_orm)):
        result = await create_my_batch(data=data, user=user, db=db)

    assert result.id == BATCH_ID
    assert result.account_id == ACCOUNT_ID


@pytest.mark.asyncio
async def test_api_list_batches():
    """34. GET /corporate/accounts/me/batches — 200."""
    from app.api.v1.corporate_batch_booking import list_my_batches

    user = _mock_user()
    db = AsyncMock()
    batches = [_mock_batch_orm(), _mock_batch_orm()]

    with patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch(f"{_ROUTER}.list_batches", new=AsyncMock(return_value=batches)):
        result = await list_my_batches(status=None, user=user, db=db)

    assert len(result) == 2


@pytest.mark.asyncio
async def test_api_get_batch():
    """35. GET /corporate/accounts/me/batches/{id} — 200."""
    from app.api.v1.corporate_batch_booking import get_my_batch

    user = _mock_user()
    db = AsyncMock()
    batch_orm = _mock_batch_orm()

    with patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch(f"{_ROUTER}.get_batch", new=AsyncMock(return_value=batch_orm)):
        result = await get_my_batch(batch_id=BATCH_ID, user=user, db=db)

    assert result.id == BATCH_ID


@pytest.mark.asyncio
async def test_api_submit_batch():
    """36. POST /corporate/accounts/me/batches/{id}/submit — 200."""
    from app.api.v1.corporate_batch_booking import submit_my_batch

    user = _mock_user(user_id=ADMIN_ID)
    db = AsyncMock()
    submitted_orm = _make_batch(status=BatchBookingStatus.SUBMITTED)
    submitted_orm.submitted_at = NOW

    with patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch(f"{_ROUTER}.submit_batch", new=AsyncMock(return_value=submitted_orm)):
        result = await submit_my_batch(batch_id=BATCH_ID, user=user, db=db)

    assert result.status == BatchBookingStatus.SUBMITTED


@pytest.mark.asyncio
async def test_api_cancel_batch():
    """37. DELETE /corporate/accounts/me/batches/{id} — 200 with reason."""
    from app.api.v1.corporate_batch_booking import cancel_my_batch

    user = _mock_user(user_id=ADMIN_ID)
    db = AsyncMock()
    cancelled_orm = _make_batch(status=BatchBookingStatus.CANCELLED)
    cancelled_orm.cancelled_at = NOW
    cancelled_orm.cancellation_reason = "Event postponed"
    body = CancelBatchRequest(reason="Event postponed")

    with patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch(f"{_ROUTER}.cancel_batch", new=AsyncMock(return_value=cancelled_orm)):
        result = await cancel_my_batch(batch_id=BATCH_ID, body=body, user=user, db=db)

    assert result.status == BatchBookingStatus.CANCELLED
    assert result.cancellation_reason == "Event postponed"


@pytest.mark.asyncio
async def test_api_admin_list_batches():
    """38. GET /admin/corporate/accounts/{id}/batches — 200 admin path."""
    from app.api.v1.corporate_batch_booking import admin_list_batches

    admin = _mock_user(user_id=ADMIN_ID)
    db = AsyncMock()
    batches = [_mock_batch_orm()]

    with patch(f"{_ROUTER}.list_batches", new=AsyncMock(return_value=batches)):
        result = await admin_list_batches(
            account_id=ACCOUNT_ID, status=None, _admin=admin, db=db
        )

    assert len(result) == 1
    assert result[0].account_id == ACCOUNT_ID
