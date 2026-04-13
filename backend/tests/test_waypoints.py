"""Tests for multi-stop rides (waypoints).

Covers model, enums, schema validation, service logic (add, update, remove,
status transitions, bulk add, reorder), routing integration, and API endpoints.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.ride import Ride, RideStatus
from app.models.waypoint import RideWaypoint, WaypointStatus
from app.schemas.waypoint import (
    WaypointCreate,
    WaypointListResponse,
    WaypointResponse,
    WaypointUpdate,
    MultiStopFareEstimateRequest,
)
from app.services.waypoints import (
    MAX_WAYPOINTS,
    WaypointError,
    _MODIFIABLE_STATUSES,
    _VALID_TRANSITIONS,
    add_waypoint,
    add_waypoints_bulk,
    get_next_pending_waypoint,
    get_waypoints,
    remove_waypoint,
    update_waypoint,
    update_waypoint_status,
)


# ===========================================================================
# RideWaypoint Model Tests
# ===========================================================================


class TestRideWaypointModel:
    def test_table_name(self):
        assert RideWaypoint.__tablename__ == "ride_waypoints"

    def test_has_ride_id_column(self):
        cols = {c.name for c in RideWaypoint.__table__.columns}
        assert "ride_id" in cols

    def test_has_order_column(self):
        cols = {c.name for c in RideWaypoint.__table__.columns}
        assert "order" in cols

    def test_has_address_column(self):
        cols = {c.name for c in RideWaypoint.__table__.columns}
        assert "address" in cols

    def test_has_lat_column(self):
        cols = {c.name for c in RideWaypoint.__table__.columns}
        assert "lat" in cols

    def test_has_lng_column(self):
        cols = {c.name for c in RideWaypoint.__table__.columns}
        assert "lng" in cols

    def test_has_status_column(self):
        cols = {c.name for c in RideWaypoint.__table__.columns}
        assert "status" in cols

    def test_has_wait_time_minutes_column(self):
        cols = {c.name for c in RideWaypoint.__table__.columns}
        assert "wait_time_minutes" in cols

    def test_has_notes_column(self):
        cols = {c.name for c in RideWaypoint.__table__.columns}
        assert "notes" in cols

    def test_has_estimated_arrival_at_column(self):
        cols = {c.name for c in RideWaypoint.__table__.columns}
        assert "estimated_arrival_at" in cols

    def test_has_actual_arrival_at_column(self):
        cols = {c.name for c in RideWaypoint.__table__.columns}
        assert "actual_arrival_at" in cols

    def test_has_departed_at_column(self):
        cols = {c.name for c in RideWaypoint.__table__.columns}
        assert "departed_at" in cols

    def test_has_created_at_column(self):
        cols = {c.name for c in RideWaypoint.__table__.columns}
        assert "created_at" in cols

    def test_has_updated_at_column(self):
        cols = {c.name for c in RideWaypoint.__table__.columns}
        assert "updated_at" in cols

    def test_ride_id_is_indexed(self):
        col = RideWaypoint.__table__.columns["ride_id"]
        assert col.index is True

    def test_ride_id_has_foreign_key(self):
        col = RideWaypoint.__table__.columns["ride_id"]
        fks = [fk.target_fullname for fk in col.foreign_keys]
        assert "rides.id" in fks


# ===========================================================================
# WaypointStatus Enum Tests
# ===========================================================================


class TestWaypointStatus:
    def test_pending_value(self):
        assert WaypointStatus.PENDING == "pending"

    def test_arrived_value(self):
        assert WaypointStatus.ARRIVED == "arrived"

    def test_departed_value(self):
        assert WaypointStatus.DEPARTED == "departed"

    def test_skipped_value(self):
        assert WaypointStatus.SKIPPED == "skipped"

    def test_all_statuses(self):
        expected = {"pending", "arrived", "departed", "skipped"}
        actual = {s.value for s in WaypointStatus}
        assert actual == expected

    def test_is_str_enum(self):
        assert isinstance(WaypointStatus.PENDING, str)


# ===========================================================================
# Schema Tests — WaypointCreate
# ===========================================================================


class TestWaypointCreateSchema:
    def test_valid_create(self):
        wp = WaypointCreate(
            address="123 Main St", lat=40.7128, lng=-74.0060
        )
        assert wp.address == "123 Main St"
        assert wp.wait_time_minutes == 3  # default

    def test_custom_wait_time(self):
        wp = WaypointCreate(
            address="Stop", lat=40.0, lng=-74.0, wait_time_minutes=5
        )
        assert wp.wait_time_minutes == 5

    def test_notes_optional(self):
        wp = WaypointCreate(
            address="Stop", lat=40.0, lng=-74.0, notes="Pick up groceries"
        )
        assert wp.notes == "Pick up groceries"

    def test_notes_default_none(self):
        wp = WaypointCreate(address="Stop", lat=40.0, lng=-74.0)
        assert wp.notes is None

    def test_wait_time_too_low(self):
        with pytest.raises(ValueError, match="wait_time_minutes"):
            WaypointCreate(
                address="Stop", lat=40.0, lng=-74.0, wait_time_minutes=0
            )

    def test_wait_time_too_high(self):
        with pytest.raises(ValueError, match="wait_time_minutes"):
            WaypointCreate(
                address="Stop", lat=40.0, lng=-74.0, wait_time_minutes=11
            )

    def test_wait_time_min_boundary(self):
        wp = WaypointCreate(
            address="Stop", lat=40.0, lng=-74.0, wait_time_minutes=1
        )
        assert wp.wait_time_minutes == 1

    def test_wait_time_max_boundary(self):
        wp = WaypointCreate(
            address="Stop", lat=40.0, lng=-74.0, wait_time_minutes=10
        )
        assert wp.wait_time_minutes == 10

    def test_lat_too_low(self):
        with pytest.raises(ValueError, match="lat"):
            WaypointCreate(address="Stop", lat=-91.0, lng=-74.0)

    def test_lat_too_high(self):
        with pytest.raises(ValueError, match="lat"):
            WaypointCreate(address="Stop", lat=91.0, lng=-74.0)

    def test_lng_too_low(self):
        with pytest.raises(ValueError, match="lng"):
            WaypointCreate(address="Stop", lat=40.0, lng=-181.0)

    def test_lng_too_high(self):
        with pytest.raises(ValueError, match="lng"):
            WaypointCreate(address="Stop", lat=40.0, lng=181.0)

    def test_boundary_coords(self):
        wp = WaypointCreate(address="Pole", lat=90.0, lng=180.0)
        assert wp.lat == 90.0
        assert wp.lng == 180.0

    def test_negative_boundary_coords(self):
        wp = WaypointCreate(address="Pole", lat=-90.0, lng=-180.0)
        assert wp.lat == -90.0
        assert wp.lng == -180.0


# ===========================================================================
# Schema Tests — WaypointUpdate
# ===========================================================================


class TestWaypointUpdateSchema:
    def test_partial_update_address(self):
        upd = WaypointUpdate(address="New Address")
        assert upd.address == "New Address"
        assert upd.lat is None

    def test_partial_update_wait_time(self):
        upd = WaypointUpdate(wait_time_minutes=7)
        assert upd.wait_time_minutes == 7

    def test_all_none_by_default(self):
        upd = WaypointUpdate()
        assert upd.address is None
        assert upd.lat is None
        assert upd.lng is None
        assert upd.wait_time_minutes is None
        assert upd.notes is None

    def test_invalid_wait_time(self):
        with pytest.raises(ValueError):
            WaypointUpdate(wait_time_minutes=15)

    def test_invalid_lat(self):
        with pytest.raises(ValueError):
            WaypointUpdate(lat=100.0)

    def test_invalid_lng(self):
        with pytest.raises(ValueError):
            WaypointUpdate(lng=200.0)


# ===========================================================================
# Schema Tests — WaypointResponse
# ===========================================================================


class TestWaypointResponseSchema:
    def test_from_attributes(self):
        assert WaypointResponse.model_config.get("from_attributes") is True

    def test_all_fields_present(self):
        fields = set(WaypointResponse.model_fields.keys())
        expected = {
            "id", "ride_id", "order", "address", "lat", "lng", "status",
            "wait_time_minutes", "notes", "estimated_arrival_at",
            "actual_arrival_at", "departed_at", "created_at", "updated_at",
        }
        assert expected.issubset(fields)


# ===========================================================================
# Schema Tests — MultiStopFareEstimateRequest
# ===========================================================================


class TestMultiStopFareEstimateRequestSchema:
    def test_valid_request(self):
        req = MultiStopFareEstimateRequest(
            pickup_lat=40.7128,
            pickup_lng=-74.006,
            dropoff_lat=40.7580,
            dropoff_lng=-73.9855,
            waypoints=[
                WaypointCreate(address="Stop 1", lat=40.73, lng=-73.99),
            ],
        )
        assert len(req.waypoints) == 1

    def test_max_three_waypoints(self):
        wps = [
            WaypointCreate(address=f"Stop {i}", lat=40.0 + i * 0.01, lng=-74.0)
            for i in range(3)
        ]
        req = MultiStopFareEstimateRequest(
            pickup_lat=40.0, pickup_lng=-74.0,
            dropoff_lat=41.0, dropoff_lng=-74.0,
            waypoints=wps,
        )
        assert len(req.waypoints) == 3

    def test_too_many_waypoints(self):
        wps = [
            WaypointCreate(address=f"Stop {i}", lat=40.0 + i * 0.01, lng=-74.0)
            for i in range(4)
        ]
        with pytest.raises(ValueError, match="Maximum 3"):
            MultiStopFareEstimateRequest(
                pickup_lat=40.0, pickup_lng=-74.0,
                dropoff_lat=41.0, dropoff_lng=-74.0,
                waypoints=wps,
            )

    def test_empty_waypoints_rejected(self):
        with pytest.raises(ValueError, match="At least 1"):
            MultiStopFareEstimateRequest(
                pickup_lat=40.0, pickup_lng=-74.0,
                dropoff_lat=41.0, dropoff_lng=-74.0,
                waypoints=[],
            )


# ===========================================================================
# Service Constants Tests
# ===========================================================================


class TestServiceConstants:
    def test_max_waypoints_is_three(self):
        assert MAX_WAYPOINTS == 3

    def test_modifiable_statuses(self):
        expected = {
            RideStatus.REQUESTED,
            RideStatus.MATCHED,
            RideStatus.DRIVER_EN_ROUTE,
            RideStatus.ARRIVED,
        }
        assert _MODIFIABLE_STATUSES == expected

    def test_in_progress_not_modifiable(self):
        assert RideStatus.IN_PROGRESS not in _MODIFIABLE_STATUSES

    def test_completed_not_modifiable(self):
        assert RideStatus.COMPLETED not in _MODIFIABLE_STATUSES

    def test_cancelled_not_modifiable(self):
        assert RideStatus.CANCELLED not in _MODIFIABLE_STATUSES


# ===========================================================================
# Status Transition Tests
# ===========================================================================


class TestStatusTransitions:
    def test_pending_can_go_to_arrived(self):
        assert WaypointStatus.ARRIVED in _VALID_TRANSITIONS[WaypointStatus.PENDING]

    def test_pending_can_go_to_skipped(self):
        assert WaypointStatus.SKIPPED in _VALID_TRANSITIONS[WaypointStatus.PENDING]

    def test_pending_cannot_go_to_departed(self):
        assert WaypointStatus.DEPARTED not in _VALID_TRANSITIONS[WaypointStatus.PENDING]

    def test_arrived_can_go_to_departed(self):
        assert WaypointStatus.DEPARTED in _VALID_TRANSITIONS[WaypointStatus.ARRIVED]

    def test_arrived_can_go_to_skipped(self):
        assert WaypointStatus.SKIPPED in _VALID_TRANSITIONS[WaypointStatus.ARRIVED]

    def test_departed_is_terminal(self):
        assert len(_VALID_TRANSITIONS[WaypointStatus.DEPARTED]) == 0

    def test_skipped_is_terminal(self):
        assert len(_VALID_TRANSITIONS[WaypointStatus.SKIPPED]) == 0

    def test_arrived_cannot_go_back_to_pending(self):
        assert WaypointStatus.PENDING not in _VALID_TRANSITIONS[WaypointStatus.ARRIVED]


# ===========================================================================
# Service Tests — add_waypoint
# ===========================================================================


def _make_mock_ride(rider_id=1, status=RideStatus.REQUESTED):
    ride = MagicMock(spec=Ride)
    ride.id = 10
    ride.rider_id = rider_id
    ride.status = status
    return ride


def _make_mock_waypoint(
    wp_id=1, ride_id=10, order=1, status=WaypointStatus.PENDING,
    address="123 Main St", lat=40.7128, lng=-74.006,
):
    wp = MagicMock(spec=RideWaypoint)
    wp.id = wp_id
    wp.ride_id = ride_id
    wp.order = order
    wp.status = status
    wp.address = address
    wp.lat = lat
    wp.lng = lng
    wp.wait_time_minutes = 3
    wp.notes = None
    wp.estimated_arrival_at = None
    wp.actual_arrival_at = None
    wp.departed_at = None
    wp.created_at = datetime(2026, 4, 12, tzinfo=timezone.utc)
    wp.updated_at = datetime(2026, 4, 12, tzinfo=timezone.utc)
    return wp


class TestAddWaypoint:
    @pytest.mark.asyncio
    async def test_add_waypoint_success(self):
        db = AsyncMock()
        ride = _make_mock_ride(rider_id=1, status=RideStatus.REQUESTED)

        # Mock get_ride_for_waypoint_ops
        with patch("app.services.waypoints.get_ride_for_waypoint_ops", return_value=ride):
            # Mock get_waypoints returning empty list (no existing waypoints)
            with patch("app.services.waypoints.get_waypoints", return_value=[]):
                wp = await add_waypoint(
                    db, ride_id=10, user_id=1,
                    address="Stop 1", lat=40.73, lng=-73.99,
                )
                # Verify db.add was called
                db.add.assert_called_once()
                db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_waypoint_max_exceeded(self):
        db = AsyncMock()
        ride = _make_mock_ride(rider_id=1, status=RideStatus.REQUESTED)
        existing = [_make_mock_waypoint(wp_id=i) for i in range(3)]

        with patch("app.services.waypoints.get_ride_for_waypoint_ops", return_value=ride):
            with patch("app.services.waypoints.get_waypoints", return_value=existing):
                with pytest.raises(WaypointError, match="Maximum 3"):
                    await add_waypoint(
                        db, ride_id=10, user_id=1,
                        address="Too many", lat=40.0, lng=-74.0,
                    )

    @pytest.mark.asyncio
    async def test_add_waypoint_wrong_user(self):
        db = AsyncMock()

        with patch(
            "app.services.waypoints.get_ride_for_waypoint_ops",
            side_effect=WaypointError("Not authorized"),
        ):
            with pytest.raises(WaypointError, match="Not authorized"):
                await add_waypoint(
                    db, ride_id=10, user_id=999,
                    address="Stop", lat=40.0, lng=-74.0,
                )

    @pytest.mark.asyncio
    async def test_add_waypoint_ride_completed(self):
        db = AsyncMock()
        ride = _make_mock_ride(rider_id=1, status=RideStatus.COMPLETED)

        with patch("app.services.waypoints.get_ride_for_waypoint_ops", return_value=ride):
            with pytest.raises(WaypointError, match="Cannot add"):
                await add_waypoint(
                    db, ride_id=10, user_id=1,
                    address="Stop", lat=40.0, lng=-74.0,
                )

    @pytest.mark.asyncio
    async def test_add_waypoint_ride_in_progress(self):
        db = AsyncMock()
        ride = _make_mock_ride(rider_id=1, status=RideStatus.IN_PROGRESS)

        with patch("app.services.waypoints.get_ride_for_waypoint_ops", return_value=ride):
            with pytest.raises(WaypointError, match="Cannot add"):
                await add_waypoint(
                    db, ride_id=10, user_id=1,
                    address="Stop", lat=40.0, lng=-74.0,
                )

    @pytest.mark.asyncio
    async def test_add_waypoint_sets_correct_order(self):
        db = AsyncMock()
        ride = _make_mock_ride(rider_id=1, status=RideStatus.MATCHED)
        existing = [_make_mock_waypoint(wp_id=1, order=1)]

        with patch("app.services.waypoints.get_ride_for_waypoint_ops", return_value=ride):
            with patch("app.services.waypoints.get_waypoints", return_value=existing):
                await add_waypoint(
                    db, ride_id=10, user_id=1,
                    address="Stop 2", lat=40.74, lng=-73.98,
                )
                # Check the waypoint added to db has order=2
                added_wp = db.add.call_args[0][0]
                assert added_wp.order == 2


# ===========================================================================
# Service Tests — add_waypoints_bulk
# ===========================================================================


class TestAddWaypointsBulk:
    @pytest.mark.asyncio
    async def test_bulk_add_success(self):
        db = AsyncMock()
        ride = _make_mock_ride(rider_id=1, status=RideStatus.REQUESTED)

        with patch("app.services.waypoints.get_ride_for_waypoint_ops", return_value=ride):
            with patch("app.services.waypoints.get_waypoints", return_value=[]):
                wps_data = [
                    {"address": "Stop 1", "lat": 40.73, "lng": -73.99},
                    {"address": "Stop 2", "lat": 40.74, "lng": -73.98},
                ]
                result = await add_waypoints_bulk(db, 10, 1, wps_data)
                assert db.add.call_count == 2
                db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_bulk_add_exceeds_max(self):
        db = AsyncMock()
        ride = _make_mock_ride(rider_id=1, status=RideStatus.REQUESTED)

        with patch("app.services.waypoints.get_ride_for_waypoint_ops", return_value=ride):
            wps_data = [
                {"address": f"Stop {i}", "lat": 40.0 + i * 0.01, "lng": -74.0}
                for i in range(4)
            ]
            with pytest.raises(WaypointError, match="Maximum 3"):
                await add_waypoints_bulk(db, 10, 1, wps_data)

    @pytest.mark.asyncio
    async def test_bulk_add_with_existing(self):
        db = AsyncMock()
        ride = _make_mock_ride(rider_id=1, status=RideStatus.REQUESTED)
        existing = [_make_mock_waypoint(wp_id=1, order=1)]

        with patch("app.services.waypoints.get_ride_for_waypoint_ops", return_value=ride):
            with patch("app.services.waypoints.get_waypoints", return_value=existing):
                wps_data = [
                    {"address": "Stop 2", "lat": 40.74, "lng": -73.98},
                    {"address": "Stop 3", "lat": 40.75, "lng": -73.97},
                    {"address": "Stop 4", "lat": 40.76, "lng": -73.96},
                ]
                # 1 existing + 3 new = 4 > max 3
                with pytest.raises(WaypointError, match="Maximum 3"):
                    await add_waypoints_bulk(db, 10, 1, wps_data)

    @pytest.mark.asyncio
    async def test_bulk_add_order_starts_after_existing(self):
        db = AsyncMock()
        ride = _make_mock_ride(rider_id=1, status=RideStatus.REQUESTED)
        existing = [_make_mock_waypoint(wp_id=1, order=1)]

        with patch("app.services.waypoints.get_ride_for_waypoint_ops", return_value=ride):
            with patch("app.services.waypoints.get_waypoints", return_value=existing):
                wps_data = [
                    {"address": "Stop 2", "lat": 40.74, "lng": -73.98},
                ]
                await add_waypoints_bulk(db, 10, 1, wps_data)
                added_wp = db.add.call_args[0][0]
                assert added_wp.order == 2

    @pytest.mark.asyncio
    async def test_bulk_add_custom_wait_time(self):
        db = AsyncMock()
        ride = _make_mock_ride(rider_id=1, status=RideStatus.REQUESTED)

        with patch("app.services.waypoints.get_ride_for_waypoint_ops", return_value=ride):
            with patch("app.services.waypoints.get_waypoints", return_value=[]):
                wps_data = [
                    {"address": "Stop", "lat": 40.73, "lng": -73.99, "wait_time_minutes": 7},
                ]
                await add_waypoints_bulk(db, 10, 1, wps_data)
                added_wp = db.add.call_args[0][0]
                assert added_wp.wait_time_minutes == 7

    @pytest.mark.asyncio
    async def test_bulk_add_default_wait_time(self):
        db = AsyncMock()
        ride = _make_mock_ride(rider_id=1, status=RideStatus.REQUESTED)

        with patch("app.services.waypoints.get_ride_for_waypoint_ops", return_value=ride):
            with patch("app.services.waypoints.get_waypoints", return_value=[]):
                wps_data = [
                    {"address": "Stop", "lat": 40.73, "lng": -73.99},
                ]
                await add_waypoints_bulk(db, 10, 1, wps_data)
                added_wp = db.add.call_args[0][0]
                assert added_wp.wait_time_minutes == 3


# ===========================================================================
# Service Tests — update_waypoint
# ===========================================================================


class TestUpdateWaypoint:
    @pytest.mark.asyncio
    async def test_update_address(self):
        db = AsyncMock()
        ride = _make_mock_ride(rider_id=1, status=RideStatus.MATCHED)
        wp = _make_mock_waypoint(wp_id=5, ride_id=10, status=WaypointStatus.PENDING)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = wp
        db.execute.return_value = mock_result

        with patch("app.services.waypoints.get_ride_for_waypoint_ops", return_value=ride):
            result = await update_waypoint(
                db, 10, 5, 1, {"address": "New Address"}
            )
            assert wp.address == "New Address"
            db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_non_pending_fails(self):
        db = AsyncMock()
        ride = _make_mock_ride(rider_id=1, status=RideStatus.MATCHED)
        wp = _make_mock_waypoint(wp_id=5, ride_id=10, status=WaypointStatus.ARRIVED)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = wp
        db.execute.return_value = mock_result

        with patch("app.services.waypoints.get_ride_for_waypoint_ops", return_value=ride):
            with pytest.raises(WaypointError, match="pending"):
                await update_waypoint(db, 10, 5, 1, {"address": "New"})

    @pytest.mark.asyncio
    async def test_update_waypoint_not_found(self):
        db = AsyncMock()
        ride = _make_mock_ride(rider_id=1, status=RideStatus.MATCHED)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result

        with patch("app.services.waypoints.get_ride_for_waypoint_ops", return_value=ride):
            with pytest.raises(WaypointError, match="not found"):
                await update_waypoint(db, 10, 999, 1, {"address": "New"})

    @pytest.mark.asyncio
    async def test_update_completed_ride_fails(self):
        db = AsyncMock()
        ride = _make_mock_ride(rider_id=1, status=RideStatus.COMPLETED)

        with patch("app.services.waypoints.get_ride_for_waypoint_ops", return_value=ride):
            with pytest.raises(WaypointError, match="Cannot update"):
                await update_waypoint(db, 10, 5, 1, {"address": "New"})


# ===========================================================================
# Service Tests — remove_waypoint
# ===========================================================================


class TestRemoveWaypoint:
    @pytest.mark.asyncio
    async def test_remove_pending_success(self):
        db = AsyncMock()
        ride = _make_mock_ride(rider_id=1, status=RideStatus.REQUESTED)
        wp = _make_mock_waypoint(wp_id=5, ride_id=10, order=1, status=WaypointStatus.PENDING)

        mock_result1 = MagicMock()
        mock_result1.scalar_one_or_none.return_value = wp

        # Mock for remaining waypoints query
        mock_remaining = MagicMock()
        mock_remaining.scalars.return_value.all.return_value = []

        db.execute.side_effect = [mock_result1, mock_remaining]

        with patch("app.services.waypoints.get_ride_for_waypoint_ops", return_value=ride):
            await remove_waypoint(db, 10, 5, 1)
            db.delete.assert_called_once_with(wp)
            db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_remove_non_pending_fails(self):
        db = AsyncMock()
        ride = _make_mock_ride(rider_id=1, status=RideStatus.REQUESTED)
        wp = _make_mock_waypoint(wp_id=5, status=WaypointStatus.ARRIVED)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = wp
        db.execute.return_value = mock_result

        with patch("app.services.waypoints.get_ride_for_waypoint_ops", return_value=ride):
            with pytest.raises(WaypointError, match="pending"):
                await remove_waypoint(db, 10, 5, 1)

    @pytest.mark.asyncio
    async def test_remove_not_found(self):
        db = AsyncMock()
        ride = _make_mock_ride(rider_id=1, status=RideStatus.REQUESTED)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result

        with patch("app.services.waypoints.get_ride_for_waypoint_ops", return_value=ride):
            with pytest.raises(WaypointError, match="not found"):
                await remove_waypoint(db, 10, 999, 1)

    @pytest.mark.asyncio
    async def test_remove_reorders_remaining(self):
        db = AsyncMock()
        ride = _make_mock_ride(rider_id=1, status=RideStatus.REQUESTED)
        wp = _make_mock_waypoint(wp_id=5, ride_id=10, order=1, status=WaypointStatus.PENDING)

        # Remaining waypoints after removal
        wp2 = _make_mock_waypoint(wp_id=6, order=2)
        wp3 = _make_mock_waypoint(wp_id=7, order=3)

        mock_result1 = MagicMock()
        mock_result1.scalar_one_or_none.return_value = wp

        mock_remaining = MagicMock()
        mock_remaining.scalars.return_value.all.return_value = [wp2, wp3]

        db.execute.side_effect = [mock_result1, mock_remaining]

        with patch("app.services.waypoints.get_ride_for_waypoint_ops", return_value=ride):
            await remove_waypoint(db, 10, 5, 1)
            assert wp2.order == 1
            assert wp3.order == 2


# ===========================================================================
# Service Tests — update_waypoint_status
# ===========================================================================


class TestUpdateWaypointStatus:
    @pytest.mark.asyncio
    async def test_pending_to_arrived(self):
        db = AsyncMock()
        wp = _make_mock_waypoint(wp_id=5, status=WaypointStatus.PENDING)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = wp
        db.execute.return_value = mock_result

        result = await update_waypoint_status(db, 10, 5, WaypointStatus.ARRIVED)
        assert wp.status == WaypointStatus.ARRIVED
        assert wp.actual_arrival_at is not None

    @pytest.mark.asyncio
    async def test_arrived_to_departed(self):
        db = AsyncMock()
        wp = _make_mock_waypoint(wp_id=5, status=WaypointStatus.ARRIVED)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = wp
        db.execute.return_value = mock_result

        result = await update_waypoint_status(db, 10, 5, WaypointStatus.DEPARTED)
        assert wp.status == WaypointStatus.DEPARTED
        assert wp.departed_at is not None

    @pytest.mark.asyncio
    async def test_pending_to_skipped(self):
        db = AsyncMock()
        wp = _make_mock_waypoint(wp_id=5, status=WaypointStatus.PENDING)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = wp
        db.execute.return_value = mock_result

        result = await update_waypoint_status(db, 10, 5, WaypointStatus.SKIPPED)
        assert wp.status == WaypointStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_arrived_to_skipped(self):
        db = AsyncMock()
        wp = _make_mock_waypoint(wp_id=5, status=WaypointStatus.ARRIVED)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = wp
        db.execute.return_value = mock_result

        result = await update_waypoint_status(db, 10, 5, WaypointStatus.SKIPPED)
        assert wp.status == WaypointStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_invalid_transition_departed_to_pending(self):
        db = AsyncMock()
        wp = _make_mock_waypoint(wp_id=5, status=WaypointStatus.DEPARTED)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = wp
        db.execute.return_value = mock_result

        with pytest.raises(WaypointError, match="Cannot transition"):
            await update_waypoint_status(db, 10, 5, WaypointStatus.PENDING)

    @pytest.mark.asyncio
    async def test_invalid_transition_skipped_to_arrived(self):
        db = AsyncMock()
        wp = _make_mock_waypoint(wp_id=5, status=WaypointStatus.SKIPPED)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = wp
        db.execute.return_value = mock_result

        with pytest.raises(WaypointError, match="Cannot transition"):
            await update_waypoint_status(db, 10, 5, WaypointStatus.ARRIVED)

    @pytest.mark.asyncio
    async def test_invalid_transition_pending_to_departed(self):
        db = AsyncMock()
        wp = _make_mock_waypoint(wp_id=5, status=WaypointStatus.PENDING)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = wp
        db.execute.return_value = mock_result

        with pytest.raises(WaypointError, match="Cannot transition"):
            await update_waypoint_status(db, 10, 5, WaypointStatus.DEPARTED)

    @pytest.mark.asyncio
    async def test_waypoint_not_found(self):
        db = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result

        with pytest.raises(WaypointError, match="not found"):
            await update_waypoint_status(db, 10, 999, WaypointStatus.ARRIVED)


# ===========================================================================
# Service Tests — get_ride_for_waypoint_ops
# ===========================================================================


class TestGetRideForWaypointOps:
    @pytest.mark.asyncio
    async def test_ride_not_found(self):
        from app.services.waypoints import get_ride_for_waypoint_ops

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result

        with pytest.raises(WaypointError, match="not found"):
            await get_ride_for_waypoint_ops(db, 999, 1)

    @pytest.mark.asyncio
    async def test_wrong_rider(self):
        from app.services.waypoints import get_ride_for_waypoint_ops

        db = AsyncMock()
        ride = _make_mock_ride(rider_id=1)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = ride
        db.execute.return_value = mock_result

        with pytest.raises(WaypointError, match="Not authorized"):
            await get_ride_for_waypoint_ops(db, 10, 999)

    @pytest.mark.asyncio
    async def test_success(self):
        from app.services.waypoints import get_ride_for_waypoint_ops

        db = AsyncMock()
        ride = _make_mock_ride(rider_id=1)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = ride
        db.execute.return_value = mock_result

        result = await get_ride_for_waypoint_ops(db, 10, 1)
        assert result == ride


# ===========================================================================
# Routing Tests — get_multi_stop_route
# ===========================================================================


class TestMultiStopRouting:
    @pytest.mark.asyncio
    async def test_multi_stop_route_success(self):
        from app.services.routing import get_multi_stop_route

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "code": "Ok",
            "routes": [{
                "distance": 15000,  # 15 km
                "duration": 1200,   # 20 min
                "geometry": {"type": "LineString", "coordinates": []},
                "legs": [
                    {"distance": 5000, "duration": 400},
                    {"distance": 4000, "duration": 350},
                    {"distance": 6000, "duration": 450},
                ],
            }],
        }

        with patch("app.services.routing.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await get_multi_stop_route(
                40.7, -74.0, 40.8, -73.9,
                [(40.73, -73.99), (40.75, -73.97)],
            )
            assert result["distance_km"] == 15.0
            assert result["duration_min"] == 20.0
            assert len(result["legs"]) == 3
            assert result["legs"][0]["distance_km"] == 5.0
            assert result["legs"][1]["distance_km"] == 4.0
            assert result["legs"][2]["distance_km"] == 6.0

    @pytest.mark.asyncio
    async def test_multi_stop_route_no_route(self):
        from app.services.routing import RoutingError, get_multi_stop_route

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": "NoRoute", "routes": []}

        with patch("app.services.routing.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(RoutingError, match="No route"):
                await get_multi_stop_route(
                    40.7, -74.0, 40.8, -73.9, [(40.73, -73.99)],
                )

    @pytest.mark.asyncio
    async def test_multi_stop_route_server_error(self):
        from app.services.routing import RoutingError, get_multi_stop_route

        mock_response = MagicMock()
        mock_response.status_code = 500

        with patch("app.services.routing.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(RoutingError, match="500"):
                await get_multi_stop_route(
                    40.7, -74.0, 40.8, -73.9, [(40.73, -73.99)],
                )

    @pytest.mark.asyncio
    async def test_multi_stop_single_waypoint(self):
        from app.services.routing import get_multi_stop_route

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "code": "Ok",
            "routes": [{
                "distance": 10000,
                "duration": 900,
                "geometry": {"type": "LineString", "coordinates": []},
                "legs": [
                    {"distance": 4000, "duration": 400},
                    {"distance": 6000, "duration": 500},
                ],
            }],
        }

        with patch("app.services.routing.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await get_multi_stop_route(
                40.7, -74.0, 40.8, -73.9, [(40.75, -73.95)],
            )
            assert len(result["legs"]) == 2


# ===========================================================================
# API Endpoint Tests (mock DB + auth)
# ===========================================================================


def _make_mock_user(user_id=1, role="rider"):
    user = MagicMock()
    user.id = user_id
    user.role = role
    return user


class TestWaypointListEndpoint:
    @pytest.mark.asyncio
    async def test_list_waypoints(self):
        from fastapi.testclient import TestClient

        from app.api.deps import get_current_user
        from app.db.database import get_db
        from app.main import app

        mock_user = _make_mock_user(1)
        mock_db = AsyncMock()

        # Mock the get_waypoints service call
        with patch("app.api.v1.waypoints.get_waypoints", return_value=[]):
            app.dependency_overrides[get_current_user] = lambda: mock_user
            app.dependency_overrides[get_db] = lambda: mock_db
            try:
                client = TestClient(app)
                resp = client.get("/api/v1/rides/10/waypoints")
                assert resp.status_code == 200
                data = resp.json()
                assert data["ride_id"] == 10
                assert data["waypoints"] == []
                assert data["total_waypoints"] == 0
            finally:
                app.dependency_overrides.clear()


class TestWaypointCreateEndpoint:
    @pytest.mark.asyncio
    async def test_create_waypoint_success(self):
        from fastapi.testclient import TestClient

        from app.api.deps import get_current_user
        from app.db.database import get_db
        from app.main import app

        mock_user = _make_mock_user(1)
        mock_db = AsyncMock()

        wp = _make_mock_waypoint(wp_id=1, ride_id=10, order=1)
        # Make the mock work with model_validate
        wp_dict = {
            "id": 1, "ride_id": 10, "order": 1, "address": "123 Main St",
            "lat": 40.7128, "lng": -74.006, "status": "pending",
            "wait_time_minutes": 3, "notes": None,
            "estimated_arrival_at": None, "actual_arrival_at": None,
            "departed_at": None,
            "created_at": datetime(2026, 4, 12, tzinfo=timezone.utc),
            "updated_at": datetime(2026, 4, 12, tzinfo=timezone.utc),
        }

        with patch("app.api.v1.waypoints.add_waypoint", return_value=MagicMock(**wp_dict)):
            app.dependency_overrides[get_current_user] = lambda: mock_user
            app.dependency_overrides[get_db] = lambda: mock_db
            try:
                client = TestClient(app)
                resp = client.post(
                    "/api/v1/rides/10/waypoints",
                    json={
                        "address": "123 Main St",
                        "lat": 40.7128,
                        "lng": -74.006,
                    },
                )
                assert resp.status_code == 201
                data = resp.json()
                assert data["ride_id"] == 10
                assert data["order"] == 1
            finally:
                app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_create_waypoint_ride_not_found(self):
        from fastapi.testclient import TestClient

        from app.api.deps import get_current_user
        from app.db.database import get_db
        from app.main import app

        mock_user = _make_mock_user(1)
        mock_db = AsyncMock()

        with patch(
            "app.api.v1.waypoints.add_waypoint",
            side_effect=WaypointError("Ride not found"),
        ):
            app.dependency_overrides[get_current_user] = lambda: mock_user
            app.dependency_overrides[get_db] = lambda: mock_db
            try:
                client = TestClient(app)
                resp = client.post(
                    "/api/v1/rides/999/waypoints",
                    json={"address": "Stop", "lat": 40.0, "lng": -74.0},
                )
                assert resp.status_code == 404
            finally:
                app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_create_waypoint_not_authorized(self):
        from fastapi.testclient import TestClient

        from app.api.deps import get_current_user
        from app.db.database import get_db
        from app.main import app

        mock_user = _make_mock_user(999)
        mock_db = AsyncMock()

        with patch(
            "app.api.v1.waypoints.add_waypoint",
            side_effect=WaypointError("Not authorized"),
        ):
            app.dependency_overrides[get_current_user] = lambda: mock_user
            app.dependency_overrides[get_db] = lambda: mock_db
            try:
                client = TestClient(app)
                resp = client.post(
                    "/api/v1/rides/10/waypoints",
                    json={"address": "Stop", "lat": 40.0, "lng": -74.0},
                )
                assert resp.status_code == 403
            finally:
                app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_create_waypoint_max_exceeded(self):
        from fastapi.testclient import TestClient

        from app.api.deps import get_current_user
        from app.db.database import get_db
        from app.main import app

        mock_user = _make_mock_user(1)
        mock_db = AsyncMock()

        with patch(
            "app.api.v1.waypoints.add_waypoint",
            side_effect=WaypointError("Maximum 3 waypoints per ride"),
        ):
            app.dependency_overrides[get_current_user] = lambda: mock_user
            app.dependency_overrides[get_db] = lambda: mock_db
            try:
                client = TestClient(app)
                resp = client.post(
                    "/api/v1/rides/10/waypoints",
                    json={"address": "Stop", "lat": 40.0, "lng": -74.0},
                )
                assert resp.status_code == 409
            finally:
                app.dependency_overrides.clear()


class TestWaypointDeleteEndpoint:
    @pytest.mark.asyncio
    async def test_delete_success(self):
        from fastapi.testclient import TestClient

        from app.api.deps import get_current_user
        from app.db.database import get_db
        from app.main import app

        mock_user = _make_mock_user(1)
        mock_db = AsyncMock()

        with patch("app.api.v1.waypoints.remove_waypoint", return_value=None):
            app.dependency_overrides[get_current_user] = lambda: mock_user
            app.dependency_overrides[get_db] = lambda: mock_db
            try:
                client = TestClient(app)
                resp = client.delete("/api/v1/rides/10/waypoints/5")
                assert resp.status_code == 204
            finally:
                app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_delete_not_found(self):
        from fastapi.testclient import TestClient

        from app.api.deps import get_current_user
        from app.db.database import get_db
        from app.main import app

        mock_user = _make_mock_user(1)
        mock_db = AsyncMock()

        with patch(
            "app.api.v1.waypoints.remove_waypoint",
            side_effect=WaypointError("Waypoint not found"),
        ):
            app.dependency_overrides[get_current_user] = lambda: mock_user
            app.dependency_overrides[get_db] = lambda: mock_db
            try:
                client = TestClient(app)
                resp = client.delete("/api/v1/rides/10/waypoints/999")
                assert resp.status_code == 404
            finally:
                app.dependency_overrides.clear()


class TestWaypointUpdateEndpoint:
    @pytest.mark.asyncio
    async def test_update_success(self):
        from fastapi.testclient import TestClient

        from app.api.deps import get_current_user
        from app.db.database import get_db
        from app.main import app

        mock_user = _make_mock_user(1)
        mock_db = AsyncMock()

        wp_dict = {
            "id": 5, "ride_id": 10, "order": 1, "address": "New Address",
            "lat": 40.72, "lng": -74.01, "status": "pending",
            "wait_time_minutes": 3, "notes": None,
            "estimated_arrival_at": None, "actual_arrival_at": None,
            "departed_at": None,
            "created_at": datetime(2026, 4, 12, tzinfo=timezone.utc),
            "updated_at": datetime(2026, 4, 12, tzinfo=timezone.utc),
        }

        with patch("app.api.v1.waypoints.update_waypoint", return_value=MagicMock(**wp_dict)):
            app.dependency_overrides[get_current_user] = lambda: mock_user
            app.dependency_overrides[get_db] = lambda: mock_db
            try:
                client = TestClient(app)
                resp = client.patch(
                    "/api/v1/rides/10/waypoints/5",
                    json={"address": "New Address"},
                )
                assert resp.status_code == 200
                assert resp.json()["address"] == "New Address"
            finally:
                app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_update_no_fields(self):
        from fastapi.testclient import TestClient

        from app.api.deps import get_current_user
        from app.db.database import get_db
        from app.main import app

        mock_user = _make_mock_user(1)
        mock_db = AsyncMock()

        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            client = TestClient(app)
            resp = client.patch(
                "/api/v1/rides/10/waypoints/5",
                json={},
            )
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()


class TestWaypointStatusEndpoints:
    @pytest.mark.asyncio
    async def test_arrive_success(self):
        from fastapi.testclient import TestClient

        from app.api.deps import require_driver
        from app.db.database import get_db
        from app.main import app

        mock_driver = _make_mock_user(2, role="driver")
        mock_db = AsyncMock()

        wp_dict = {
            "id": 5, "ride_id": 10, "order": 1, "address": "123 Main St",
            "lat": 40.7128, "lng": -74.006, "status": "arrived",
            "wait_time_minutes": 3, "notes": None,
            "estimated_arrival_at": None,
            "actual_arrival_at": datetime(2026, 4, 12, 10, 30, tzinfo=timezone.utc),
            "departed_at": None,
            "created_at": datetime(2026, 4, 12, tzinfo=timezone.utc),
            "updated_at": datetime(2026, 4, 12, 10, 30, tzinfo=timezone.utc),
        }

        with patch(
            "app.api.v1.waypoints.update_waypoint_status",
            return_value=MagicMock(**wp_dict),
        ):
            app.dependency_overrides[require_driver] = lambda: mock_driver
            app.dependency_overrides[get_db] = lambda: mock_db
            try:
                client = TestClient(app)
                resp = client.post("/api/v1/rides/10/waypoints/5/arrive")
                assert resp.status_code == 200
                assert resp.json()["status"] == "arrived"
            finally:
                app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_depart_success(self):
        from fastapi.testclient import TestClient

        from app.api.deps import require_driver
        from app.db.database import get_db
        from app.main import app

        mock_driver = _make_mock_user(2, role="driver")
        mock_db = AsyncMock()

        wp_dict = {
            "id": 5, "ride_id": 10, "order": 1, "address": "123 Main St",
            "lat": 40.7128, "lng": -74.006, "status": "departed",
            "wait_time_minutes": 3, "notes": None,
            "estimated_arrival_at": None,
            "actual_arrival_at": datetime(2026, 4, 12, 10, 30, tzinfo=timezone.utc),
            "departed_at": datetime(2026, 4, 12, 10, 33, tzinfo=timezone.utc),
            "created_at": datetime(2026, 4, 12, tzinfo=timezone.utc),
            "updated_at": datetime(2026, 4, 12, 10, 33, tzinfo=timezone.utc),
        }

        with patch(
            "app.api.v1.waypoints.update_waypoint_status",
            return_value=MagicMock(**wp_dict),
        ):
            app.dependency_overrides[require_driver] = lambda: mock_driver
            app.dependency_overrides[get_db] = lambda: mock_db
            try:
                client = TestClient(app)
                resp = client.post("/api/v1/rides/10/waypoints/5/depart")
                assert resp.status_code == 200
                assert resp.json()["status"] == "departed"
            finally:
                app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_skip_success(self):
        from fastapi.testclient import TestClient

        from app.api.deps import get_current_user
        from app.db.database import get_db
        from app.main import app

        mock_user = _make_mock_user(1)
        mock_db = AsyncMock()

        wp_dict = {
            "id": 5, "ride_id": 10, "order": 1, "address": "123 Main St",
            "lat": 40.7128, "lng": -74.006, "status": "skipped",
            "wait_time_minutes": 3, "notes": None,
            "estimated_arrival_at": None, "actual_arrival_at": None,
            "departed_at": None,
            "created_at": datetime(2026, 4, 12, tzinfo=timezone.utc),
            "updated_at": datetime(2026, 4, 12, tzinfo=timezone.utc),
        }

        with patch(
            "app.api.v1.waypoints.update_waypoint_status",
            return_value=MagicMock(**wp_dict),
        ):
            app.dependency_overrides[get_current_user] = lambda: mock_user
            app.dependency_overrides[get_db] = lambda: mock_db
            try:
                client = TestClient(app)
                resp = client.post("/api/v1/rides/10/waypoints/5/skip")
                assert resp.status_code == 200
                assert resp.json()["status"] == "skipped"
            finally:
                app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_invalid_transition(self):
        from fastapi.testclient import TestClient

        from app.api.deps import require_driver
        from app.db.database import get_db
        from app.main import app

        mock_driver = _make_mock_user(2, role="driver")
        mock_db = AsyncMock()

        with patch(
            "app.api.v1.waypoints.update_waypoint_status",
            side_effect=WaypointError("Cannot transition from departed to pending"),
        ):
            app.dependency_overrides[require_driver] = lambda: mock_driver
            app.dependency_overrides[get_db] = lambda: mock_db
            try:
                client = TestClient(app)
                resp = client.post("/api/v1/rides/10/waypoints/5/arrive")
                assert resp.status_code == 409
            finally:
                app.dependency_overrides.clear()


# ===========================================================================
# Ride Schema Integration Tests — WaypointInput in RideRequest
# ===========================================================================


class TestRideRequestWithWaypoints:
    def test_ride_request_no_waypoints(self):
        from app.schemas.ride import RideRequest

        req = RideRequest(
            pickup={"lat": 40.7, "lng": -74.0},
            dropoff={"lat": 40.8, "lng": -73.9},
            pickup_address="Start",
            dropoff_address="End",
        )
        assert req.waypoints is None

    def test_ride_request_with_waypoints(self):
        from app.schemas.ride import RideRequest

        req = RideRequest(
            pickup={"lat": 40.7, "lng": -74.0},
            dropoff={"lat": 40.8, "lng": -73.9},
            pickup_address="Start",
            dropoff_address="End",
            waypoints=[
                {"address": "Stop 1", "lat": 40.73, "lng": -73.99},
                {"address": "Stop 2", "lat": 40.75, "lng": -73.97},
            ],
        )
        assert len(req.waypoints) == 2
        assert req.waypoints[0].address == "Stop 1"

    def test_fare_estimate_request_with_waypoints(self):
        from app.schemas.ride import FareEstimateRequest

        req = FareEstimateRequest(
            pickup={"lat": 40.7, "lng": -74.0},
            dropoff={"lat": 40.8, "lng": -73.9},
            waypoints=[
                {"address": "Stop 1", "lat": 40.73, "lng": -73.99},
            ],
        )
        assert len(req.waypoints) == 1

    def test_fare_estimate_request_no_waypoints(self):
        from app.schemas.ride import FareEstimateRequest

        req = FareEstimateRequest(
            pickup={"lat": 40.7, "lng": -74.0},
            dropoff={"lat": 40.8, "lng": -73.9},
        )
        assert req.waypoints is None
