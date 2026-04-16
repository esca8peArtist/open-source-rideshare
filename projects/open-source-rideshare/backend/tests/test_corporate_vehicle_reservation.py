"""Tests for the Corporate Vehicle Reservation Booking feature.

Service layer (async, mocked DB):
   1.  create_reservation — success: creates with status=pending
   2.  create_reservation — 404 when vehicle not in account
   3.  create_reservation — 409 when vehicle is inactive
   4.  create_reservation — 409 on overlapping reservation
   5.  get_reservation — success: returns existing reservation
   6.  get_reservation — 404 when not found
   7.  list_reservations — returns all reservations for account
   8.  list_reservations — filters by fleet_vehicle_id
   9.  list_reservations — filters by status
  10.  list_reservations — filters by from_time / to_time
  11.  list_member_reservations — returns reservations for given user
  12.  update_reservation — success when pending
  13.  update_reservation — 409 when confirmed
  14.  update_reservation — 409 when new time overlaps
  15.  confirm_reservation — success from pending
  16.  confirm_reservation — 409 when not pending
  17.  cancel_reservation — success from pending
  18.  cancel_reservation — success from confirmed
  19.  cancel_reservation — 409 when already completed
  20.  cancel_reservation — 409 when already no_show
  21.  complete_reservation — success from confirmed
  22.  complete_reservation — 409 when not confirmed
  23.  no_show_reservation — success from confirmed
  24.  no_show_reservation — 409 when not confirmed
  25.  check_vehicle_availability — available (no conflicts)
  26.  check_vehicle_availability — unavailable (has conflicts)
  27.  get_reservation_summary — correct counts across all statuses
  28.  list_all_platform — returns all without filter
  29.  list_all_platform — filters by account_id

Schema validation:
  30.  VehicleReservationCreate — requires fleet_vehicle_id
  31.  VehicleReservationCreate — requires start_time
  32.  VehicleReservationCreate — requires end_time
  33.  VehicleReservationCreate — optional fields default to None
  34.  VehicleReservationUpdate — all fields optional
  35.  VehicleReservationCancel — cancellation_reason optional
  36.  VehicleReservationResponse — from_attributes construction
  37.  VehicleAvailabilityResponse — structure with conflicts
  38.  VehicleReservationSummaryResponse — structure with all status counts

API layer (service functions patched):
  39.  POST /vehicle-reservations/ — 201 member can create reservation
  40.  POST /vehicle-reservations/ — 404 when vehicle not found
  41.  POST /vehicle-reservations/ — 409 on overlap conflict
  42.  GET  /vehicle-reservations/ — 200 member can list
  43.  GET  /vehicle-reservations/ — 404 when account not found
  44.  GET  /vehicle-reservations/my — 200 member can get own
  45.  GET  /vehicle-reservations/summary — 200 member can get summary
  46.  GET  /vehicle-reservations/{reservation_id} — 200 member can get one
  47.  GET  /vehicle-reservations/{reservation_id} — 404 when not found
  48.  POST /vehicle-reservations/{reservation_id}/cancel — 200 member cancels own
  49.  POST /vehicle-reservations/{reservation_id}/cancel — 403 member cancels other's
  50.  POST /vehicle-reservations/{reservation_id}/cancel — 200 admin cancels any
  51.  PUT  /vehicle-reservations/{reservation_id} — 200 admin can update
  52.  PUT  /vehicle-reservations/{reservation_id} — 403 non-admin cannot update
  53.  PUT  /vehicle-reservations/{reservation_id} — 409 on conflict
  54.  POST /vehicle-reservations/{reservation_id}/confirm — 200 admin can confirm
  55.  POST /vehicle-reservations/{reservation_id}/confirm — 403 non-admin cannot confirm
  56.  POST /vehicle-reservations/{reservation_id}/confirm — 409 not pending
  57.  POST /vehicle-reservations/{reservation_id}/complete — 200 admin can complete
  58.  POST /vehicle-reservations/{reservation_id}/complete — 403 non-admin cannot
  59.  POST /vehicle-reservations/{reservation_id}/no-show — 200 admin can no-show
  60.  POST /vehicle-reservations/{reservation_id}/no-show — 403 non-admin cannot
  61.  GET  /fleet-vehicles/{vehicle_id}/availability — 200 admin can check
  62.  GET  /fleet-vehicles/{vehicle_id}/availability — 403 non-admin cannot check
  63.  GET  /platform/corporate/vehicle-reservations/ — 200 platform-admin list all
  64.  GET  /platform/corporate/vehicle-reservations/ — 200 with account_id filter
  65.  GET  /platform/corporate/vehicle-reservations/{account_id} — 200 per-account
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models.corporate_vehicle_reservation import (
    CorporateVehicleReservation,
    ReservationStatus,
)
from app.schemas.corporate_vehicle_reservation import (
    VehicleAvailabilityResponse,
    VehicleReservationCancel,
    VehicleReservationCreate,
    VehicleReservationResponse,
    VehicleReservationSummaryResponse,
    VehicleReservationUpdate,
)
from app.services.corporate_vehicle_reservation_service import (
    cancel_reservation,
    check_vehicle_availability,
    complete_reservation,
    confirm_reservation,
    create_reservation,
    get_reservation,
    get_reservation_summary,
    list_all_platform,
    list_member_reservations,
    list_reservations,
    no_show_reservation,
    update_reservation,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACCOUNT_ID = 42
VEHICLE_ID = uuid.uuid4()
RESERVATION_ID = uuid.uuid4()
USER_ID = 10
ADMIN_ID = 1

_SERVICE = "app.services.corporate_vehicle_reservation_service"
_ROUTER = "app.api.v1.corporate_vehicle_reservation"

_NOW = datetime(2026, 4, 16, 9, 0, 0, tzinfo=timezone.utc)
_START = datetime(2026, 4, 20, 9, 0, 0, tzinfo=timezone.utc)
_END = datetime(2026, 4, 20, 17, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_reservation(
    reservation_id: uuid.UUID = RESERVATION_ID,
    account_id: int = ACCOUNT_ID,
    fleet_vehicle_id: uuid.UUID = VEHICLE_ID,
    reserved_by_id: int | None = USER_ID,
    approved_by_id: int | None = None,
    start_time: datetime = _START,
    end_time: datetime = _END,
    purpose: str | None = "Client site visit",
    pickup_location: str | None = "HQ",
    dropoff_location: str | None = "Client office",
    notes: str | None = None,
    trip_purpose_id: uuid.UUID | None = None,
    cost_center_id: uuid.UUID | None = None,
    status: ReservationStatus = ReservationStatus.pending,
    cancelled_at: datetime | None = None,
    cancelled_by_id: int | None = None,
    cancellation_reason: str | None = None,
) -> CorporateVehicleReservation:
    r = CorporateVehicleReservation()
    r.id = reservation_id
    r.account_id = account_id
    r.fleet_vehicle_id = fleet_vehicle_id
    r.reserved_by_id = reserved_by_id
    r.approved_by_id = approved_by_id
    r.start_time = start_time
    r.end_time = end_time
    r.purpose = purpose
    r.pickup_location = pickup_location
    r.dropoff_location = dropoff_location
    r.notes = notes
    r.trip_purpose_id = trip_purpose_id
    r.cost_center_id = cost_center_id
    r.status = status
    r.cancelled_at = cancelled_at
    r.cancelled_by_id = cancelled_by_id
    r.cancellation_reason = cancellation_reason
    r.created_at = _NOW
    r.updated_at = _NOW
    return r


def _reservation_response(r: CorporateVehicleReservation) -> VehicleReservationResponse:
    return VehicleReservationResponse(
        id=r.id,
        account_id=r.account_id,
        fleet_vehicle_id=r.fleet_vehicle_id,
        reserved_by_id=r.reserved_by_id,
        approved_by_id=r.approved_by_id,
        start_time=r.start_time,
        end_time=r.end_time,
        purpose=r.purpose,
        pickup_location=r.pickup_location,
        dropoff_location=r.dropoff_location,
        notes=r.notes,
        trip_purpose_id=r.trip_purpose_id,
        cost_center_id=r.cost_center_id,
        status=r.status.value,
        cancelled_at=r.cancelled_at,
        cancelled_by_id=r.cancelled_by_id,
        cancellation_reason=r.cancellation_reason,
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


# ---------------------------------------------------------------------------
# Shared mock DB helpers
# ---------------------------------------------------------------------------


def _db_scalar(scalar=None):
    """DB that always returns the same scalar from execute()."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    result.scalars.return_value.all.return_value = [scalar] if scalar is not None else []
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()

    def _refresh(obj):
        if not getattr(obj, "created_at", None):
            obj.created_at = _NOW
        if hasattr(obj, "updated_at") and not getattr(obj, "updated_at", None):
            obj.updated_at = _NOW

    db.refresh = AsyncMock(side_effect=_refresh)
    return db


def _db_scalars_all(rows: list):
    """DB whose execute().scalars().all() returns rows."""
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    result.scalar_one_or_none.return_value = rows[0] if rows else None
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()

    def _refresh(obj):
        if not getattr(obj, "created_at", None):
            obj.created_at = _NOW
        if hasattr(obj, "updated_at") and not getattr(obj, "updated_at", None):
            obj.updated_at = _NOW

    db.refresh = AsyncMock(side_effect=_refresh)
    return db


def _db_sequence(*results):
    """DB whose execute() returns successive MagicMocks from results list.

    Each element should be:
    - a single ORM object -> scalar_one_or_none
    - a list of ORM objects -> scalars().all()
    - None -> scalar_one_or_none returns None, scalars().all() returns []
    """
    db = AsyncMock()
    mock_results = []
    for r in results:
        m = MagicMock()
        if isinstance(r, list):
            m.scalar_one_or_none.return_value = None
            m.scalars.return_value.all.return_value = r
        else:
            m.scalar_one_or_none.return_value = r
            m.scalars.return_value.all.return_value = [r] if r is not None else []
        mock_results.append(m)

    db.execute = AsyncMock(side_effect=mock_results)
    db.commit = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()

    def _refresh(obj):
        if not getattr(obj, "created_at", None):
            obj.created_at = _NOW
        if hasattr(obj, "updated_at") and not getattr(obj, "updated_at", None):
            obj.updated_at = _NOW

    db.refresh = AsyncMock(side_effect=_refresh)
    return db


def _make_fleet_vehicle(is_active: bool = True):
    """Create a minimal mock fleet vehicle."""
    from app.models.corporate_fleet_vehicle import CorporateFleetVehicle
    v = CorporateFleetVehicle()
    v.id = VEHICLE_ID
    v.account_id = ACCOUNT_ID
    v.name = "Test Van"
    v.is_active = is_active
    v.created_at = _NOW
    v.updated_at = _NOW
    return v


# ---------------------------------------------------------------------------
# Service tests: create_reservation  (1–4)
# ---------------------------------------------------------------------------


class TestCreateReservation:
    """Tests for create_reservation."""

    @pytest.mark.asyncio
    async def test_creates_with_status_pending(self):
        """1. Creates reservation with status=pending."""
        vehicle = _make_fleet_vehicle(is_active=True)
        # Sequence: fetch vehicle, overlap check returns no conflicts
        db = _db_sequence(vehicle, [])
        payload = VehicleReservationCreate(
            fleet_vehicle_id=VEHICLE_ID,
            start_time=_START,
            end_time=_END,
        )
        result = await create_reservation(db, ACCOUNT_ID, USER_ID, payload)
        assert result.status == "pending"
        assert result.account_id == ACCOUNT_ID
        assert result.reserved_by_id == USER_ID
        db.add.assert_called_once()
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_404_when_vehicle_not_in_account(self):
        """2. Raises 404 when vehicle does not belong to this account."""
        db = _db_scalar(None)
        payload = VehicleReservationCreate(
            fleet_vehicle_id=VEHICLE_ID,
            start_time=_START,
            end_time=_END,
        )
        with pytest.raises(HTTPException) as exc_info:
            await create_reservation(db, ACCOUNT_ID, USER_ID, payload)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_raises_409_when_vehicle_inactive(self):
        """3. Raises 409 when the fleet vehicle is not active."""
        vehicle = _make_fleet_vehicle(is_active=False)
        db = _db_scalar(vehicle)
        payload = VehicleReservationCreate(
            fleet_vehicle_id=VEHICLE_ID,
            start_time=_START,
            end_time=_END,
        )
        with pytest.raises(HTTPException) as exc_info:
            await create_reservation(db, ACCOUNT_ID, USER_ID, payload)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_raises_409_on_overlap(self):
        """4. Raises 409 when an overlapping reservation exists."""
        vehicle = _make_fleet_vehicle(is_active=True)
        conflict = _make_reservation(status=ReservationStatus.confirmed)
        # Sequence: fetch vehicle, overlap check returns one conflict
        db = _db_sequence(vehicle, [conflict])
        payload = VehicleReservationCreate(
            fleet_vehicle_id=VEHICLE_ID,
            start_time=_START,
            end_time=_END,
        )
        with pytest.raises(HTTPException) as exc_info:
            await create_reservation(db, ACCOUNT_ID, USER_ID, payload)
        assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# Service tests: get_reservation  (5–6)
# ---------------------------------------------------------------------------


class TestGetReservation:
    """Tests for get_reservation."""

    @pytest.mark.asyncio
    async def test_returns_existing_reservation(self):
        """5. Returns the reservation when found."""
        reservation = _make_reservation()
        db = _db_scalar(reservation)
        result = await get_reservation(db, ACCOUNT_ID, RESERVATION_ID)
        assert result.id == RESERVATION_ID
        assert result.status == "pending"

    @pytest.mark.asyncio
    async def test_raises_404_when_not_found(self):
        """6. Raises 404 when reservation not found."""
        db = _db_scalar(None)
        with pytest.raises(HTTPException) as exc_info:
            await get_reservation(db, ACCOUNT_ID, RESERVATION_ID)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service tests: list_reservations  (7–10)
# ---------------------------------------------------------------------------


class TestListReservations:
    """Tests for list_reservations."""

    @pytest.mark.asyncio
    async def test_returns_all_for_account(self):
        """7. Returns all reservations for the account."""
        r1 = _make_reservation(reservation_id=uuid.uuid4())
        r2 = _make_reservation(reservation_id=uuid.uuid4())
        db = _db_scalars_all([r1, r2])
        result = await list_reservations(db, ACCOUNT_ID)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_filters_by_fleet_vehicle_id(self):
        """8. Passes fleet_vehicle_id filter."""
        r1 = _make_reservation()
        db = _db_scalars_all([r1])
        result = await list_reservations(db, ACCOUNT_ID, fleet_vehicle_id=VEHICLE_ID)
        assert len(result) == 1
        assert result[0].fleet_vehicle_id == VEHICLE_ID

    @pytest.mark.asyncio
    async def test_filters_by_status(self):
        """9. Passes status filter."""
        r1 = _make_reservation(status=ReservationStatus.confirmed)
        db = _db_scalars_all([r1])
        result = await list_reservations(db, ACCOUNT_ID, status=ReservationStatus.confirmed)
        assert len(result) == 1
        assert result[0].status == "confirmed"

    @pytest.mark.asyncio
    async def test_filters_by_date_range(self):
        """10. Passes from_time and to_time filters."""
        r1 = _make_reservation(start_time=_START, end_time=_END)
        db = _db_scalars_all([r1])
        result = await list_reservations(db, ACCOUNT_ID, from_time=_START, to_time=_END)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Service tests: list_member_reservations  (11)
# ---------------------------------------------------------------------------


class TestListMemberReservations:
    """Tests for list_member_reservations."""

    @pytest.mark.asyncio
    async def test_returns_reservations_for_user(self):
        """11. Returns reservations for the specified user."""
        r1 = _make_reservation(reserved_by_id=USER_ID)
        r2 = _make_reservation(reservation_id=uuid.uuid4(), reserved_by_id=USER_ID)
        db = _db_scalars_all([r1, r2])
        result = await list_member_reservations(db, ACCOUNT_ID, USER_ID)
        assert len(result) == 2
        assert all(r.reserved_by_id == USER_ID for r in result)


# ---------------------------------------------------------------------------
# Service tests: update_reservation  (12–14)
# ---------------------------------------------------------------------------


class TestUpdateReservation:
    """Tests for update_reservation."""

    @pytest.mark.asyncio
    async def test_success_when_pending(self):
        """12. Updates fields on a pending reservation."""
        reservation = _make_reservation(status=ReservationStatus.pending)
        # Sequence: fetch reservation, no overlap
        db = _db_sequence(reservation, [])
        payload = VehicleReservationUpdate(purpose="Updated purpose")
        result = await update_reservation(db, ACCOUNT_ID, RESERVATION_ID, payload)
        assert reservation.purpose == "Updated purpose"
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_409_when_confirmed(self):
        """13. Raises 409 when reservation is in confirmed status."""
        reservation = _make_reservation(status=ReservationStatus.confirmed)
        db = _db_scalar(reservation)
        payload = VehicleReservationUpdate(purpose="New purpose")
        with pytest.raises(HTTPException) as exc_info:
            await update_reservation(db, ACCOUNT_ID, RESERVATION_ID, payload)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_raises_409_when_new_time_overlaps(self):
        """14. Raises 409 when new time window overlaps another reservation."""
        reservation = _make_reservation(status=ReservationStatus.pending)
        other = _make_reservation(
            reservation_id=uuid.uuid4(), status=ReservationStatus.confirmed
        )
        # Sequence: fetch reservation, overlap check returns conflict
        db = _db_sequence(reservation, [other])
        new_start = datetime(2026, 4, 20, 8, 0, 0, tzinfo=timezone.utc)
        new_end = datetime(2026, 4, 20, 18, 0, 0, tzinfo=timezone.utc)
        payload = VehicleReservationUpdate(start_time=new_start, end_time=new_end)
        with pytest.raises(HTTPException) as exc_info:
            await update_reservation(db, ACCOUNT_ID, RESERVATION_ID, payload)
        assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# Service tests: confirm_reservation  (15–16)
# ---------------------------------------------------------------------------


class TestConfirmReservation:
    """Tests for confirm_reservation."""

    @pytest.mark.asyncio
    async def test_success_from_pending(self):
        """15. Confirms a pending reservation, sets status=confirmed."""
        reservation = _make_reservation(status=ReservationStatus.pending)
        db = _db_scalar(reservation)
        result = await confirm_reservation(db, ACCOUNT_ID, RESERVATION_ID, ADMIN_ID)
        assert reservation.status == ReservationStatus.confirmed
        assert reservation.approved_by_id == ADMIN_ID
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_409_when_not_pending(self):
        """16. Raises 409 when reservation is not pending."""
        reservation = _make_reservation(status=ReservationStatus.confirmed)
        db = _db_scalar(reservation)
        with pytest.raises(HTTPException) as exc_info:
            await confirm_reservation(db, ACCOUNT_ID, RESERVATION_ID, ADMIN_ID)
        assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# Service tests: cancel_reservation  (17–20)
# ---------------------------------------------------------------------------


class TestCancelReservation:
    """Tests for cancel_reservation."""

    @pytest.mark.asyncio
    async def test_success_from_pending(self):
        """17. Cancels a pending reservation."""
        reservation = _make_reservation(status=ReservationStatus.pending)
        db = _db_scalar(reservation)
        data = VehicleReservationCancel(cancellation_reason="Plans changed")
        result = await cancel_reservation(db, ACCOUNT_ID, RESERVATION_ID, USER_ID, data)
        assert reservation.status == ReservationStatus.cancelled
        assert reservation.cancelled_by_id == USER_ID
        assert reservation.cancellation_reason == "Plans changed"
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_success_from_confirmed(self):
        """18. Cancels a confirmed reservation."""
        reservation = _make_reservation(status=ReservationStatus.confirmed)
        db = _db_scalar(reservation)
        data = VehicleReservationCancel()
        result = await cancel_reservation(db, ACCOUNT_ID, RESERVATION_ID, ADMIN_ID, data)
        assert reservation.status == ReservationStatus.cancelled

    @pytest.mark.asyncio
    async def test_raises_409_when_completed(self):
        """19. Raises 409 when reservation is already completed."""
        reservation = _make_reservation(status=ReservationStatus.completed)
        db = _db_scalar(reservation)
        data = VehicleReservationCancel()
        with pytest.raises(HTTPException) as exc_info:
            await cancel_reservation(db, ACCOUNT_ID, RESERVATION_ID, USER_ID, data)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_raises_409_when_no_show(self):
        """20. Raises 409 when reservation is already a no-show."""
        reservation = _make_reservation(status=ReservationStatus.no_show)
        db = _db_scalar(reservation)
        data = VehicleReservationCancel()
        with pytest.raises(HTTPException) as exc_info:
            await cancel_reservation(db, ACCOUNT_ID, RESERVATION_ID, USER_ID, data)
        assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# Service tests: complete_reservation  (21–22)
# ---------------------------------------------------------------------------


class TestCompleteReservation:
    """Tests for complete_reservation."""

    @pytest.mark.asyncio
    async def test_success_from_confirmed(self):
        """21. Marks a confirmed reservation as completed."""
        reservation = _make_reservation(status=ReservationStatus.confirmed)
        db = _db_scalar(reservation)
        result = await complete_reservation(db, ACCOUNT_ID, RESERVATION_ID)
        assert reservation.status == ReservationStatus.completed
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_409_when_not_confirmed(self):
        """22. Raises 409 when reservation is not confirmed."""
        reservation = _make_reservation(status=ReservationStatus.pending)
        db = _db_scalar(reservation)
        with pytest.raises(HTTPException) as exc_info:
            await complete_reservation(db, ACCOUNT_ID, RESERVATION_ID)
        assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# Service tests: no_show_reservation  (23–24)
# ---------------------------------------------------------------------------


class TestNoShowReservation:
    """Tests for no_show_reservation."""

    @pytest.mark.asyncio
    async def test_success_from_confirmed(self):
        """23. Marks a confirmed reservation as no-show."""
        reservation = _make_reservation(status=ReservationStatus.confirmed)
        db = _db_scalar(reservation)
        result = await no_show_reservation(db, ACCOUNT_ID, RESERVATION_ID)
        assert reservation.status == ReservationStatus.no_show
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_409_when_not_confirmed(self):
        """24. Raises 409 when reservation is not confirmed."""
        reservation = _make_reservation(status=ReservationStatus.pending)
        db = _db_scalar(reservation)
        with pytest.raises(HTTPException) as exc_info:
            await no_show_reservation(db, ACCOUNT_ID, RESERVATION_ID)
        assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# Service tests: check_vehicle_availability  (25–26)
# ---------------------------------------------------------------------------


class TestCheckVehicleAvailability:
    """Tests for check_vehicle_availability."""

    @pytest.mark.asyncio
    async def test_available_when_no_conflicts(self):
        """25. Returns is_available=True when no conflicts."""
        vehicle = _make_fleet_vehicle()
        # Sequence: fetch vehicle, no conflicts
        db = _db_sequence(vehicle, [])
        result = await check_vehicle_availability(
            db, ACCOUNT_ID, VEHICLE_ID, _START, _END
        )
        assert result.is_available is True
        assert len(result.conflicts) == 0
        assert result.fleet_vehicle_id == VEHICLE_ID

    @pytest.mark.asyncio
    async def test_unavailable_when_has_conflicts(self):
        """26. Returns is_available=False with conflicts listed."""
        vehicle = _make_fleet_vehicle()
        conflict = _make_reservation(status=ReservationStatus.confirmed)
        # Sequence: fetch vehicle, one conflict
        db = _db_sequence(vehicle, [conflict])
        result = await check_vehicle_availability(
            db, ACCOUNT_ID, VEHICLE_ID, _START, _END
        )
        assert result.is_available is False
        assert len(result.conflicts) == 1


# ---------------------------------------------------------------------------
# Service tests: get_reservation_summary  (27)
# ---------------------------------------------------------------------------


class TestGetReservationSummary:
    """Tests for get_reservation_summary."""

    @pytest.mark.asyncio
    async def test_returns_correct_counts(self):
        """27. Returns correct aggregate counts by status."""
        rows = [
            _make_reservation(reservation_id=uuid.uuid4(), status=ReservationStatus.pending),
            _make_reservation(reservation_id=uuid.uuid4(), status=ReservationStatus.pending),
            _make_reservation(reservation_id=uuid.uuid4(), status=ReservationStatus.confirmed),
            _make_reservation(reservation_id=uuid.uuid4(), status=ReservationStatus.cancelled),
            _make_reservation(reservation_id=uuid.uuid4(), status=ReservationStatus.completed),
            _make_reservation(reservation_id=uuid.uuid4(), status=ReservationStatus.no_show),
        ]
        db = _db_scalars_all(rows)
        result = await get_reservation_summary(db, ACCOUNT_ID)
        assert result.total == 6
        assert result.pending == 2
        assert result.confirmed == 1
        assert result.cancelled == 1
        assert result.completed == 1
        assert result.no_show == 1


# ---------------------------------------------------------------------------
# Service tests: list_all_platform  (28–29)
# ---------------------------------------------------------------------------


class TestListAllPlatform:
    """Tests for list_all_platform."""

    @pytest.mark.asyncio
    async def test_returns_all_without_filter(self):
        """28. Returns all reservations across accounts when no filter."""
        r1 = _make_reservation(reservation_id=uuid.uuid4(), account_id=1)
        r2 = _make_reservation(reservation_id=uuid.uuid4(), account_id=2)
        db = _db_scalars_all([r1, r2])
        result = await list_all_platform(db)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_filters_by_account_id(self):
        """29. Filters to a specific account when account_id provided."""
        r1 = _make_reservation(reservation_id=uuid.uuid4(), account_id=ACCOUNT_ID)
        db = _db_scalars_all([r1])
        result = await list_all_platform(db, account_id=ACCOUNT_ID)
        assert len(result) == 1
        assert result[0].account_id == ACCOUNT_ID


# ---------------------------------------------------------------------------
# Schema tests  (30–38)
# ---------------------------------------------------------------------------


class TestVehicleReservationCreate:
    """Schema validation for VehicleReservationCreate."""

    def test_requires_fleet_vehicle_id(self):
        """30. fleet_vehicle_id is required."""
        with pytest.raises(ValidationError):
            VehicleReservationCreate(start_time=_START, end_time=_END)

    def test_requires_start_time(self):
        """31. start_time is required."""
        with pytest.raises(ValidationError):
            VehicleReservationCreate(fleet_vehicle_id=VEHICLE_ID, end_time=_END)

    def test_requires_end_time(self):
        """32. end_time is required."""
        with pytest.raises(ValidationError):
            VehicleReservationCreate(fleet_vehicle_id=VEHICLE_ID, start_time=_START)

    def test_optional_fields_default_to_none(self):
        """33. All optional fields default to None."""
        schema = VehicleReservationCreate(
            fleet_vehicle_id=VEHICLE_ID, start_time=_START, end_time=_END
        )
        assert schema.purpose is None
        assert schema.pickup_location is None
        assert schema.dropoff_location is None
        assert schema.notes is None
        assert schema.trip_purpose_id is None
        assert schema.cost_center_id is None


class TestVehicleReservationUpdate:
    """Schema validation for VehicleReservationUpdate."""

    def test_all_fields_optional(self):
        """34. All fields optional — empty construction is valid."""
        schema = VehicleReservationUpdate()
        assert schema.start_time is None
        assert schema.end_time is None
        assert schema.purpose is None
        assert schema.pickup_location is None
        assert schema.dropoff_location is None
        assert schema.notes is None


class TestVehicleReservationCancel:
    """Schema validation for VehicleReservationCancel."""

    def test_cancellation_reason_optional(self):
        """35. cancellation_reason defaults to None."""
        schema = VehicleReservationCancel()
        assert schema.cancellation_reason is None


class TestResponseSchemas:
    """Tests for response schema construction."""

    def test_vehicle_reservation_response_from_attributes(self):
        """36. VehicleReservationResponse constructs from ORM attributes."""
        r = _make_reservation()
        response = VehicleReservationResponse.model_validate(r)
        assert response.id == RESERVATION_ID
        assert response.status == "pending"
        assert response.reserved_by_id == USER_ID

    def test_vehicle_availability_response_structure(self):
        """37. VehicleAvailabilityResponse carries fleet_vehicle_id, is_available, conflicts."""
        r = _make_reservation()
        resp = _reservation_response(r)
        avail = VehicleAvailabilityResponse(
            fleet_vehicle_id=VEHICLE_ID,
            is_available=False,
            conflicts=[resp],
        )
        assert avail.fleet_vehicle_id == VEHICLE_ID
        assert avail.is_available is False
        assert len(avail.conflicts) == 1

    def test_vehicle_reservation_summary_structure(self):
        """38. VehicleReservationSummaryResponse constructs with all status counts."""
        summary = VehicleReservationSummaryResponse(
            total=10,
            pending=3,
            confirmed=2,
            cancelled=2,
            completed=2,
            no_show=1,
        )
        assert summary.total == 10
        assert summary.pending == 3
        assert summary.no_show == 1


# ---------------------------------------------------------------------------
# API layer tests  (39–65)
# ---------------------------------------------------------------------------

_BASE_URL = f"/api/v1/corporate/{ACCOUNT_ID}/vehicle-reservations"
_FLEET_URL = f"/api/v1/corporate/{ACCOUNT_ID}/fleet-vehicles"
_PLATFORM_URL = "/api/v1/platform/corporate/vehicle-reservations"

client = TestClient(app)


def _make_user(user_id: int = USER_ID, is_admin: bool = False):
    user = MagicMock()
    user.id = user_id
    user.is_admin = is_admin
    return user


def _mock_account():
    account = MagicMock()
    account.id = ACCOUNT_ID
    return account


def _dep_overrides(user_id: int = USER_ID, is_admin: bool = False):
    """Return dependency override dict for FastAPI DI injection."""
    from app.api.deps import get_current_user, get_db, require_admin

    async def _user():
        return _make_user(user_id=user_id, is_admin=is_admin)

    async def _db():
        return AsyncMock()

    async def _admin():
        return _make_user(user_id=ADMIN_ID, is_admin=True)

    return {
        get_current_user: _user,
        get_db: _db,
        require_admin: _admin,
    }


class TestCreateReservationEndpoint:
    """POST /corporate/{account_id}/vehicle-reservations/"""

    def test_member_can_create_reservation(self):
        """39. 201 — member can create a reservation."""
        r = _make_reservation()
        r_resp = _reservation_response(r)

        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(f"{_ROUTER}.create_reservation", new=AsyncMock(return_value=r_resp)),
        ):
            app.dependency_overrides.update(_dep_overrides())
            response = client.post(
                f"{_BASE_URL}/",
                json={
                    "fleet_vehicle_id": str(VEHICLE_ID),
                    "start_time": _START.isoformat(),
                    "end_time": _END.isoformat(),
                },
            )
            app.dependency_overrides.clear()
        assert response.status_code == 201

    def test_404_when_vehicle_not_found(self):
        """40. 404 when fleet vehicle not found."""
        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(
                f"{_ROUTER}.create_reservation",
                new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Not found")),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides())
            response = client.post(
                f"{_BASE_URL}/",
                json={
                    "fleet_vehicle_id": str(VEHICLE_ID),
                    "start_time": _START.isoformat(),
                    "end_time": _END.isoformat(),
                },
            )
            app.dependency_overrides.clear()
        assert response.status_code == 404

    def test_409_on_overlap_conflict(self):
        """41. 409 on overlapping reservation conflict."""
        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(
                f"{_ROUTER}.create_reservation",
                new=AsyncMock(side_effect=HTTPException(status_code=409, detail="Conflict")),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides())
            response = client.post(
                f"{_BASE_URL}/",
                json={
                    "fleet_vehicle_id": str(VEHICLE_ID),
                    "start_time": _START.isoformat(),
                    "end_time": _END.isoformat(),
                },
            )
            app.dependency_overrides.clear()
        assert response.status_code == 409


class TestListReservationsEndpoint:
    """GET /corporate/{account_id}/vehicle-reservations/"""

    def test_member_can_list(self):
        """42. 200 — member can list reservations."""
        r_resp = _reservation_response(_make_reservation())

        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(f"{_ROUTER}.list_reservations", new=AsyncMock(return_value=[r_resp])),
        ):
            app.dependency_overrides.update(_dep_overrides())
            response = client.get(f"{_BASE_URL}/")
            app.dependency_overrides.clear()
        assert response.status_code == 200

    def test_404_when_account_not_found(self):
        """43. 404 when corporate account not found."""
        with patch(
            f"{_ROUTER}.get_account",
            new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Not found")),
        ):
            app.dependency_overrides.update(_dep_overrides())
            response = client.get(f"{_BASE_URL}/")
            app.dependency_overrides.clear()
        assert response.status_code == 404


class TestListMyReservationsEndpoint:
    """GET /corporate/{account_id}/vehicle-reservations/my"""

    def test_member_can_get_own(self):
        """44. 200 — member can get their own reservations."""
        r_resp = _reservation_response(_make_reservation())

        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(f"{_ROUTER}.list_member_reservations", new=AsyncMock(return_value=[r_resp])),
        ):
            app.dependency_overrides.update(_dep_overrides())
            response = client.get(f"{_BASE_URL}/my")
            app.dependency_overrides.clear()
        assert response.status_code == 200


class TestGetReservationSummaryEndpoint:
    """GET /corporate/{account_id}/vehicle-reservations/summary"""

    def test_member_can_get_summary(self):
        """45. 200 — member can get reservation summary."""
        summary = VehicleReservationSummaryResponse(
            total=5, pending=2, confirmed=1, cancelled=1, completed=1, no_show=0
        )

        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(f"{_ROUTER}.get_reservation_summary", new=AsyncMock(return_value=summary)),
        ):
            app.dependency_overrides.update(_dep_overrides())
            response = client.get(f"{_BASE_URL}/summary")
            app.dependency_overrides.clear()
        assert response.status_code == 200


class TestGetReservationEndpoint:
    """GET /corporate/{account_id}/vehicle-reservations/{reservation_id}"""

    def test_member_can_get_one(self):
        """46. 200 — member can get a single reservation."""
        r_resp = _reservation_response(_make_reservation())

        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(f"{_ROUTER}.get_reservation", new=AsyncMock(return_value=r_resp)),
        ):
            app.dependency_overrides.update(_dep_overrides())
            response = client.get(f"{_BASE_URL}/{RESERVATION_ID}")
            app.dependency_overrides.clear()
        assert response.status_code == 200

    def test_404_when_not_found(self):
        """47. 404 when reservation not found."""
        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(
                f"{_ROUTER}.get_reservation",
                new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Not found")),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides())
            response = client.get(f"{_BASE_URL}/{RESERVATION_ID}")
            app.dependency_overrides.clear()
        assert response.status_code == 404


class TestCancelReservationEndpoint:
    """POST /corporate/{account_id}/vehicle-reservations/{reservation_id}/cancel"""

    def test_member_cancels_own(self):
        """48. 200 — member can cancel their own reservation."""
        r = _make_reservation(reserved_by_id=USER_ID)
        r_resp = _reservation_response(r)
        r_resp_cancelled = _reservation_response(
            _make_reservation(reserved_by_id=USER_ID, status=ReservationStatus.cancelled)
        )

        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(f"{_ROUTER}.get_reservation", new=AsyncMock(return_value=r_resp)),
            patch(f"{_ROUTER}._require_account_admin",
                  new=AsyncMock(side_effect=HTTPException(status_code=403, detail="Forbidden"))),
            patch(f"{_ROUTER}.cancel_reservation", new=AsyncMock(return_value=r_resp_cancelled)),
        ):
            app.dependency_overrides.update(_dep_overrides(user_id=USER_ID))
            response = client.post(f"{_BASE_URL}/{RESERVATION_ID}/cancel", json={})
            app.dependency_overrides.clear()
        assert response.status_code == 200

    def test_member_cannot_cancel_others(self):
        """49. 403 — member cannot cancel another user's reservation."""
        other_user_id = 999
        r = _make_reservation(reserved_by_id=other_user_id)
        r_resp = _reservation_response(r)

        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(f"{_ROUTER}.get_reservation", new=AsyncMock(return_value=r_resp)),
            patch(f"{_ROUTER}._require_account_admin",
                  new=AsyncMock(side_effect=HTTPException(status_code=403, detail="Forbidden"))),
        ):
            app.dependency_overrides.update(_dep_overrides(user_id=USER_ID))
            response = client.post(f"{_BASE_URL}/{RESERVATION_ID}/cancel", json={})
            app.dependency_overrides.clear()
        assert response.status_code == 403

    def test_admin_can_cancel_any(self):
        """50. 200 — admin can cancel any reservation."""
        other_user_id = 999
        r = _make_reservation(reserved_by_id=other_user_id)
        r_resp = _reservation_response(r)
        r_resp_cancelled = _reservation_response(
            _make_reservation(reserved_by_id=other_user_id, status=ReservationStatus.cancelled)
        )

        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(f"{_ROUTER}.get_reservation", new=AsyncMock(return_value=r_resp)),
            patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
            patch(f"{_ROUTER}.cancel_reservation", new=AsyncMock(return_value=r_resp_cancelled)),
        ):
            app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
            response = client.post(f"{_BASE_URL}/{RESERVATION_ID}/cancel", json={})
            app.dependency_overrides.clear()
        assert response.status_code == 200


class TestUpdateReservationEndpoint:
    """PUT /corporate/{account_id}/vehicle-reservations/{reservation_id}"""

    def test_admin_can_update(self):
        """51. 200 — admin can update a pending reservation."""
        r_resp = _reservation_response(_make_reservation())

        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
            patch(f"{_ROUTER}.update_reservation", new=AsyncMock(return_value=r_resp)),
        ):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            response = client.put(
                f"{_BASE_URL}/{RESERVATION_ID}", json={"purpose": "Updated"}
            )
            app.dependency_overrides.clear()
        assert response.status_code == 200

    def test_non_admin_cannot_update(self):
        """52. 403 — non-admin cannot update a reservation."""
        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(
                f"{_ROUTER}._require_account_admin",
                new=AsyncMock(side_effect=HTTPException(status_code=403, detail="Forbidden")),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides())
            response = client.put(
                f"{_BASE_URL}/{RESERVATION_ID}", json={"purpose": "Updated"}
            )
            app.dependency_overrides.clear()
        assert response.status_code == 403

    def test_409_on_overlap(self):
        """53. 409 when updated time window conflicts with another reservation."""
        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
            patch(
                f"{_ROUTER}.update_reservation",
                new=AsyncMock(side_effect=HTTPException(status_code=409, detail="Conflict")),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            response = client.put(
                f"{_BASE_URL}/{RESERVATION_ID}",
                json={"start_time": _START.isoformat(), "end_time": _END.isoformat()},
            )
            app.dependency_overrides.clear()
        assert response.status_code == 409


class TestConfirmReservationEndpoint:
    """POST /corporate/{account_id}/vehicle-reservations/{reservation_id}/confirm"""

    def test_admin_can_confirm(self):
        """54. 200 — admin can confirm a reservation."""
        r = _make_reservation(status=ReservationStatus.confirmed)
        r_resp = _reservation_response(r)

        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
            patch(f"{_ROUTER}.confirm_reservation", new=AsyncMock(return_value=r_resp)),
        ):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            response = client.post(f"{_BASE_URL}/{RESERVATION_ID}/confirm")
            app.dependency_overrides.clear()
        assert response.status_code == 200

    def test_non_admin_cannot_confirm(self):
        """55. 403 — non-admin cannot confirm a reservation."""
        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(
                f"{_ROUTER}._require_account_admin",
                new=AsyncMock(side_effect=HTTPException(status_code=403, detail="Forbidden")),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides())
            response = client.post(f"{_BASE_URL}/{RESERVATION_ID}/confirm")
            app.dependency_overrides.clear()
        assert response.status_code == 403

    def test_409_not_pending(self):
        """56. 409 when reservation is not pending."""
        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
            patch(
                f"{_ROUTER}.confirm_reservation",
                new=AsyncMock(side_effect=HTTPException(status_code=409, detail="Not pending")),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            response = client.post(f"{_BASE_URL}/{RESERVATION_ID}/confirm")
            app.dependency_overrides.clear()
        assert response.status_code == 409


class TestCompleteReservationEndpoint:
    """POST /corporate/{account_id}/vehicle-reservations/{reservation_id}/complete"""

    def test_admin_can_complete(self):
        """57. 200 — admin can complete a reservation."""
        r = _make_reservation(status=ReservationStatus.completed)
        r_resp = _reservation_response(r)

        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
            patch(f"{_ROUTER}.complete_reservation", new=AsyncMock(return_value=r_resp)),
        ):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            response = client.post(f"{_BASE_URL}/{RESERVATION_ID}/complete")
            app.dependency_overrides.clear()
        assert response.status_code == 200

    def test_non_admin_cannot_complete(self):
        """58. 403 — non-admin cannot complete a reservation."""
        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(
                f"{_ROUTER}._require_account_admin",
                new=AsyncMock(side_effect=HTTPException(status_code=403, detail="Forbidden")),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides())
            response = client.post(f"{_BASE_URL}/{RESERVATION_ID}/complete")
            app.dependency_overrides.clear()
        assert response.status_code == 403


class TestNoShowReservationEndpoint:
    """POST /corporate/{account_id}/vehicle-reservations/{reservation_id}/no-show"""

    def test_admin_can_mark_no_show(self):
        """59. 200 — admin can mark a reservation as no-show."""
        r = _make_reservation(status=ReservationStatus.no_show)
        r_resp = _reservation_response(r)

        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
            patch(f"{_ROUTER}.no_show_reservation", new=AsyncMock(return_value=r_resp)),
        ):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            response = client.post(f"{_BASE_URL}/{RESERVATION_ID}/no-show")
            app.dependency_overrides.clear()
        assert response.status_code == 200

    def test_non_admin_cannot_mark_no_show(self):
        """60. 403 — non-admin cannot mark no-show."""
        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(
                f"{_ROUTER}._require_account_admin",
                new=AsyncMock(side_effect=HTTPException(status_code=403, detail="Forbidden")),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides())
            response = client.post(f"{_BASE_URL}/{RESERVATION_ID}/no-show")
            app.dependency_overrides.clear()
        assert response.status_code == 403


class TestCheckAvailabilityEndpoint:
    """GET /corporate/{account_id}/fleet-vehicles/{vehicle_id}/availability"""

    def test_admin_can_check_availability(self):
        """61. 200 — admin can check vehicle availability."""
        avail = VehicleAvailabilityResponse(
            fleet_vehicle_id=VEHICLE_ID,
            is_available=True,
            conflicts=[],
        )

        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
            patch(f"{_ROUTER}.check_vehicle_availability", new=AsyncMock(return_value=avail)),
        ):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            response = client.get(
                f"{_FLEET_URL}/{VEHICLE_ID}/availability",
                params={
                    "start_time": _START.isoformat(),
                    "end_time": _END.isoformat(),
                },
            )
            app.dependency_overrides.clear()
        assert response.status_code == 200

    def test_non_admin_cannot_check_availability(self):
        """62. 403 — non-admin cannot check availability."""
        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(
                f"{_ROUTER}._require_account_admin",
                new=AsyncMock(side_effect=HTTPException(status_code=403, detail="Forbidden")),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides())
            response = client.get(
                f"{_FLEET_URL}/{VEHICLE_ID}/availability",
                params={
                    "start_time": _START.isoformat(),
                    "end_time": _END.isoformat(),
                },
            )
            app.dependency_overrides.clear()
        assert response.status_code == 403


class TestPlatformAdminEndpoints:
    """Platform-admin vehicle reservation endpoints."""

    def test_platform_admin_can_list_all(self):
        """63. 200 — platform-admin can list all reservations."""
        r_resp = _reservation_response(_make_reservation())

        with patch(f"{_ROUTER}.list_all_platform", new=AsyncMock(return_value=[r_resp])):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            response = client.get(f"{_PLATFORM_URL}/")
            app.dependency_overrides.clear()
        assert response.status_code == 200

    def test_platform_admin_can_filter_by_account_id(self):
        """64. 200 — platform-admin can filter by account_id."""
        r_resp = _reservation_response(_make_reservation())

        with patch(f"{_ROUTER}.list_all_platform", new=AsyncMock(return_value=[r_resp])):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            response = client.get(f"{_PLATFORM_URL}/?account_id={ACCOUNT_ID}")
            app.dependency_overrides.clear()
        assert response.status_code == 200

    def test_platform_admin_can_list_per_account(self):
        """65. 200 — platform-admin can list reservations for a specific account."""
        r_resp = _reservation_response(_make_reservation())

        with patch(f"{_ROUTER}.list_all_platform", new=AsyncMock(return_value=[r_resp])):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            response = client.get(f"{_PLATFORM_URL}/{ACCOUNT_ID}")
            app.dependency_overrides.clear()
        assert response.status_code == 200
