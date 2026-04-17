"""Tests for the safety service and schemas.

Covers:
  - trigger_sos (async, mocked DB)
  - resolve_sos (async, mocked DB)
  - get_active_alerts (async, mocked DB)
  - add_emergency_contact (async, mocked DB)
  - list_emergency_contacts (async, mocked DB)
  - delete_emergency_contact (async, mocked DB)
  - create_trip_share_token (async, mocked DB)
  - get_shared_trip (async, mocked DB)
  - Pydantic schemas (SOSTriggerRequest, SOSAlertResponse, etc.)

No live database is used. All DB interactions are mocked with AsyncMock /
MagicMock following the same pattern used in test_cancellation_policies.py.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.safety import SOSStatus
from app.models.ride import RideStatus
from app.schemas.safety import (
    EmergencyContactCreate,
    EmergencyContactResponse,
    SharedTripView,
    SOSAlertResponse,
    SOSResolveRequest,
    SOSTriggerRequest,
    TripShareRequest,
    TripShareResponse,
)
from app.services.safety import (
    SHARE_TOKEN_TTL_HOURS,
    add_emergency_contact,
    create_trip_share_token,
    delete_emergency_contact,
    get_active_alerts,
    get_shared_trip,
    list_emergency_contacts,
    resolve_sos,
    trigger_sos,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UTC = timezone.utc


def _now() -> datetime:
    return datetime.now(_UTC)


def _make_ride_mock(
    ride_id=1,
    rider_id=10,
    driver_id=20,
    status=RideStatus.IN_PROGRESS,
):
    from app.models.ride import Ride
    ride = MagicMock(spec=Ride)
    ride.id = ride_id
    ride.rider_id = rider_id
    ride.driver_id = driver_id
    ride.status = status
    return ride


def _make_sos_alert_mock(
    alert_id=1,
    user_id=10,
    ride_id=1,
    status=SOSStatus.ACTIVE,
    latitude=37.7749,
    longitude=-122.4194,
    message="Help!",
    resolved_at=None,
):
    from app.models.safety import SOSAlert
    alert = MagicMock(spec=SOSAlert)
    alert.id = alert_id
    alert.user_id = user_id
    alert.ride_id = ride_id
    alert.status = status
    alert.latitude = latitude
    alert.longitude = longitude
    alert.message = message
    alert.created_at = _now()
    alert.resolved_at = resolved_at
    return alert


def _make_contact_mock(
    contact_id=1,
    user_id=10,
    name="Jane Doe",
    phone="+15551234567",
    relationship_label="spouse",
):
    from app.models.safety import EmergencyContact
    contact = MagicMock(spec=EmergencyContact)
    contact.id = contact_id
    contact.user_id = user_id
    contact.name = name
    contact.phone = phone
    contact.relationship_label = relationship_label
    contact.created_at = _now()
    return contact


def _make_share_token_mock(
    token_id=1,
    ride_id=1,
    token="abc123",
    created_by=10,
    expires_at=None,
):
    from app.models.safety import TripShareToken
    share = MagicMock(spec=TripShareToken)
    share.id = token_id
    share.ride_id = ride_id
    share.token = token
    share.created_by = created_by
    share.expires_at = expires_at or (_now() + timedelta(hours=SHARE_TOKEN_TTL_HOURS))
    share.created_at = _now()
    return share


def _db_returning(*rows):
    """Return a mock AsyncSession whose execute() returns the given rows in
    sequence. Each element is the scalar_one_or_none return value."""
    db = AsyncMock()
    results = []
    for row in rows:
        result = MagicMock()
        result.scalar_one_or_none.return_value = row
        result.scalar.return_value = row
        results.append(result)
    db.execute = AsyncMock(side_effect=results)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    return db


def _db_returning_scalars(items_list):
    """Return a mock AsyncSession whose execute() returns a list via scalars()."""
    db = AsyncMock()
    result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = items_list
    result.scalars.return_value = scalars_mock
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.delete = AsyncMock()
    return db


# ===========================================================================
# TestTriggerSos
# ===========================================================================


class TestTriggerSos:
    """Tests for trigger_sos (async service with mocked DB)."""

    @pytest.mark.asyncio
    async def test_trigger_without_ride_id_succeeds(self):
        db = _db_returning()
        # Patch notify_sos_alert at its definition site so the notification
        # module does not attempt real DB queries during the test.
        with patch("app.services.notification_events.notify_sos_alert", new_callable=AsyncMock):
            alert = await trigger_sos(
                user_id=10,
                db=db,
                ride_id=None,
                latitude=37.7,
                longitude=-122.4,
                message="Test SOS",
            )
        db.add.assert_called_once()
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_trigger_with_valid_ride_id_as_rider(self):
        ride = _make_ride_mock(ride_id=5, rider_id=10, driver_id=20)
        db = _db_returning(ride)
        with patch("app.services.notification_events.notify_sos_alert", new_callable=AsyncMock):
            alert = await trigger_sos(
                user_id=10,
                db=db,
                ride_id=5,
                latitude=37.7,
                longitude=-122.4,
            )
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_trigger_with_valid_ride_id_as_driver(self):
        ride = _make_ride_mock(ride_id=5, rider_id=10, driver_id=20)
        db = _db_returning(ride)
        with patch("app.services.notification_events.notify_sos_alert", new_callable=AsyncMock):
            alert = await trigger_sos(
                user_id=20,
                db=db,
                ride_id=5,
            )
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_trigger_ride_not_found_raises_value_error(self):
        db = _db_returning(None)  # ride not found
        with pytest.raises(ValueError, match="Ride not found"):
            await trigger_sos(user_id=10, db=db, ride_id=999)

    @pytest.mark.asyncio
    async def test_trigger_not_participant_raises_permission_error(self):
        ride = _make_ride_mock(ride_id=5, rider_id=10, driver_id=20)
        db = _db_returning(ride)
        with pytest.raises(PermissionError, match="Not a participant"):
            await trigger_sos(user_id=99, db=db, ride_id=5)

    @pytest.mark.asyncio
    async def test_trigger_notification_failure_doesnt_prevent_sos(self):
        """SOS creation must succeed even when notification throws.

        The service wraps the notification call in try/except Exception so any
        runtime error is silently swallowed. The alert must still be added.
        """
        db = _db_returning()
        with patch(
            "app.services.notification_events.notify_sos_alert",
            side_effect=RuntimeError("network error"),
        ):
            await trigger_sos(user_id=10, db=db, ride_id=None)
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_trigger_sets_active_status(self):
        db = _db_returning()
        with patch("app.services.notification_events.notify_sos_alert", new_callable=AsyncMock):
            await trigger_sos(user_id=10, db=db)
        added_alert = db.add.call_args[0][0]
        assert added_alert.status == SOSStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_trigger_sets_user_id(self):
        db = _db_returning()
        with patch("app.services.notification_events.notify_sos_alert", new_callable=AsyncMock):
            await trigger_sos(user_id=42, db=db)
        added_alert = db.add.call_args[0][0]
        assert added_alert.user_id == 42

    @pytest.mark.asyncio
    async def test_trigger_sets_coordinates(self):
        db = _db_returning()
        with patch("app.services.notification_events.notify_sos_alert", new_callable=AsyncMock):
            await trigger_sos(user_id=10, db=db, latitude=51.5, longitude=-0.12)
        added_alert = db.add.call_args[0][0]
        assert added_alert.latitude == 51.5
        assert added_alert.longitude == -0.12


# ===========================================================================
# TestResolveSos
# ===========================================================================


class TestResolveSos:
    """Tests for resolve_sos (async service with mocked DB)."""

    @pytest.mark.asyncio
    async def test_resolve_active_alert_false_alarm(self):
        alert = _make_sos_alert_mock(alert_id=1, user_id=10, status=SOSStatus.ACTIVE)
        db = _db_returning(alert)
        result = await resolve_sos(alert_id=1, user_id=10, db=db, resolution="false_alarm")
        assert result.status == SOSStatus.FALSE_ALARM
        assert result.resolved_at is not None

    @pytest.mark.asyncio
    async def test_resolve_active_alert_resolved(self):
        alert = _make_sos_alert_mock(alert_id=1, user_id=10, status=SOSStatus.ACTIVE)
        db = _db_returning(alert)
        result = await resolve_sos(alert_id=1, user_id=10, db=db, resolution="resolved")
        assert result.status == SOSStatus.RESOLVED

    @pytest.mark.asyncio
    async def test_resolve_alert_not_found_raises_value_error(self):
        db = _db_returning(None)
        with pytest.raises(ValueError, match="Alert not found"):
            await resolve_sos(alert_id=999, user_id=10, db=db)

    @pytest.mark.asyncio
    async def test_resolve_wrong_user_raises_permission_error(self):
        alert = _make_sos_alert_mock(alert_id=1, user_id=10, status=SOSStatus.ACTIVE)
        db = _db_returning(alert)
        with pytest.raises(PermissionError, match="Not authorized"):
            await resolve_sos(alert_id=1, user_id=99, db=db)

    @pytest.mark.asyncio
    async def test_resolve_already_resolved_raises_value_error(self):
        alert = _make_sos_alert_mock(alert_id=1, user_id=10, status=SOSStatus.RESOLVED)
        db = _db_returning(alert)
        with pytest.raises(ValueError, match="not active"):
            await resolve_sos(alert_id=1, user_id=10, db=db)

    @pytest.mark.asyncio
    async def test_resolve_false_alarm_alert_raises_value_error(self):
        alert = _make_sos_alert_mock(alert_id=1, user_id=10, status=SOSStatus.FALSE_ALARM)
        db = _db_returning(alert)
        with pytest.raises(ValueError, match="not active"):
            await resolve_sos(alert_id=1, user_id=10, db=db)

    @pytest.mark.asyncio
    async def test_resolve_calls_flush(self):
        alert = _make_sos_alert_mock(alert_id=1, user_id=10, status=SOSStatus.ACTIVE)
        db = _db_returning(alert)
        await resolve_sos(alert_id=1, user_id=10, db=db)
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_resolve_default_resolution_is_false_alarm(self):
        alert = _make_sos_alert_mock(alert_id=1, user_id=10, status=SOSStatus.ACTIVE)
        db = _db_returning(alert)
        result = await resolve_sos(alert_id=1, user_id=10, db=db)
        assert result.status == SOSStatus.FALSE_ALARM


# ===========================================================================
# TestGetActiveAlerts
# ===========================================================================


class TestGetActiveAlerts:
    """Tests for get_active_alerts (async service with mocked DB)."""

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_none(self):
        db = _db_returning_scalars([])
        alerts = await get_active_alerts(user_id=10, db=db)
        assert alerts == []

    @pytest.mark.asyncio
    async def test_returns_alerts_for_user(self):
        alert1 = _make_sos_alert_mock(alert_id=1, user_id=10)
        alert2 = _make_sos_alert_mock(alert_id=2, user_id=10)
        db = _db_returning_scalars([alert1, alert2])
        alerts = await get_active_alerts(user_id=10, db=db)
        assert len(alerts) == 2

    @pytest.mark.asyncio
    async def test_returns_list_type(self):
        db = _db_returning_scalars([])
        alerts = await get_active_alerts(user_id=10, db=db)
        assert isinstance(alerts, list)

    @pytest.mark.asyncio
    async def test_single_alert_returned(self):
        alert = _make_sos_alert_mock(alert_id=5, user_id=7)
        db = _db_returning_scalars([alert])
        alerts = await get_active_alerts(user_id=7, db=db)
        assert len(alerts) == 1
        assert alerts[0].id == 5


# ===========================================================================
# TestAddEmergencyContact
# ===========================================================================


class TestAddEmergencyContact:
    """Tests for add_emergency_contact (async service with mocked DB)."""

    @pytest.mark.asyncio
    async def test_contact_added_to_db(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        contact = await add_emergency_contact(
            user_id=10,
            name="Jane Doe",
            phone="+15551234567",
            db=db,
            relationship_label="spouse",
        )
        db.add.assert_called_once()
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_contact_has_correct_user_id(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        await add_emergency_contact(
            user_id=42,
            name="Bob",
            phone="+15559876543",
            db=db,
        )
        added = db.add.call_args[0][0]
        assert added.user_id == 42

    @pytest.mark.asyncio
    async def test_contact_has_correct_name(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        await add_emergency_contact(
            user_id=10,
            name="Alice Smith",
            phone="+1555000",
            db=db,
        )
        added = db.add.call_args[0][0]
        assert added.name == "Alice Smith"

    @pytest.mark.asyncio
    async def test_contact_relationship_label_optional(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        await add_emergency_contact(
            user_id=10,
            name="Bob",
            phone="+1555000",
            db=db,
            relationship_label=None,
        )
        added = db.add.call_args[0][0]
        assert added.relationship_label is None

    @pytest.mark.asyncio
    async def test_contact_phone_set_correctly(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        await add_emergency_contact(
            user_id=10,
            name="Carol",
            phone="+447911123456",
            db=db,
        )
        added = db.add.call_args[0][0]
        assert added.phone == "+447911123456"


# ===========================================================================
# TestListEmergencyContacts
# ===========================================================================


class TestListEmergencyContacts:
    """Tests for list_emergency_contacts (async service with mocked DB)."""

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_none(self):
        db = _db_returning_scalars([])
        contacts = await list_emergency_contacts(user_id=10, db=db)
        assert contacts == []

    @pytest.mark.asyncio
    async def test_returns_all_contacts(self):
        c1 = _make_contact_mock(contact_id=1, user_id=10)
        c2 = _make_contact_mock(contact_id=2, user_id=10)
        db = _db_returning_scalars([c1, c2])
        contacts = await list_emergency_contacts(user_id=10, db=db)
        assert len(contacts) == 2

    @pytest.mark.asyncio
    async def test_returns_list_type(self):
        db = _db_returning_scalars([])
        contacts = await list_emergency_contacts(user_id=10, db=db)
        assert isinstance(contacts, list)

    @pytest.mark.asyncio
    async def test_single_contact(self):
        c = _make_contact_mock(contact_id=7, user_id=5, name="Test")
        db = _db_returning_scalars([c])
        contacts = await list_emergency_contacts(user_id=5, db=db)
        assert len(contacts) == 1
        assert contacts[0].name == "Test"


# ===========================================================================
# TestDeleteEmergencyContact
# ===========================================================================


class TestDeleteEmergencyContact:
    """Tests for delete_emergency_contact (async service with mocked DB)."""

    @pytest.mark.asyncio
    async def test_delete_existing_contact_returns_true(self):
        contact = _make_contact_mock(contact_id=1, user_id=10)
        db = _db_returning(contact)
        result = await delete_emergency_contact(contact_id=1, user_id=10, db=db)
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_calls_db_delete(self):
        contact = _make_contact_mock(contact_id=1, user_id=10)
        db = _db_returning(contact)
        await delete_emergency_contact(contact_id=1, user_id=10, db=db)
        db.delete.assert_awaited_once_with(contact)

    @pytest.mark.asyncio
    async def test_delete_not_found_returns_false(self):
        db = _db_returning(None)
        result = await delete_emergency_contact(contact_id=999, user_id=10, db=db)
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_calls_flush(self):
        contact = _make_contact_mock(contact_id=1, user_id=10)
        db = _db_returning(contact)
        await delete_emergency_contact(contact_id=1, user_id=10, db=db)
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_wrong_user_returns_false(self):
        """Contact not found for this user_id returns False."""
        # The query filters by both contact_id AND user_id, so wrong user returns None
        db = _db_returning(None)
        result = await delete_emergency_contact(contact_id=1, user_id=99, db=db)
        assert result is False


# ===========================================================================
# TestCreateTripShareToken
# ===========================================================================


class TestCreateTripShareToken:
    """Tests for create_trip_share_token (async service with mocked DB)."""

    @pytest.mark.asyncio
    async def test_creates_token_for_rider(self):
        ride = _make_ride_mock(ride_id=1, rider_id=10, driver_id=20, status=RideStatus.IN_PROGRESS)
        db = _db_returning(ride)
        share = await create_trip_share_token(ride_id=1, user_id=10, db=db)
        db.add.assert_called_once()
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_creates_token_for_driver(self):
        ride = _make_ride_mock(ride_id=1, rider_id=10, driver_id=20, status=RideStatus.IN_PROGRESS)
        db = _db_returning(ride)
        share = await create_trip_share_token(ride_id=1, user_id=20, db=db)
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_ride_not_found_raises_value_error(self):
        db = _db_returning(None)
        with pytest.raises(ValueError, match="Ride not found"):
            await create_trip_share_token(ride_id=999, user_id=10, db=db)

    @pytest.mark.asyncio
    async def test_non_participant_raises_permission_error(self):
        ride = _make_ride_mock(ride_id=1, rider_id=10, driver_id=20, status=RideStatus.IN_PROGRESS)
        db = _db_returning(ride)
        with pytest.raises(PermissionError, match="Not a participant"):
            await create_trip_share_token(ride_id=1, user_id=99, db=db)

    @pytest.mark.asyncio
    async def test_completed_ride_raises_value_error(self):
        ride = _make_ride_mock(ride_id=1, rider_id=10, driver_id=20, status=RideStatus.COMPLETED)
        db = _db_returning(ride)
        with pytest.raises(ValueError, match="finished"):
            await create_trip_share_token(ride_id=1, user_id=10, db=db)

    @pytest.mark.asyncio
    async def test_cancelled_ride_raises_value_error(self):
        ride = _make_ride_mock(ride_id=1, rider_id=10, driver_id=20, status=RideStatus.CANCELLED)
        db = _db_returning(ride)
        with pytest.raises(ValueError, match="finished"):
            await create_trip_share_token(ride_id=1, user_id=10, db=db)

    @pytest.mark.asyncio
    async def test_token_has_expiry(self):
        ride = _make_ride_mock(ride_id=1, rider_id=10, driver_id=20, status=RideStatus.IN_PROGRESS)
        db = _db_returning(ride)
        await create_trip_share_token(ride_id=1, user_id=10, db=db)
        added_share = db.add.call_args[0][0]
        assert added_share.expires_at is not None

    @pytest.mark.asyncio
    async def test_token_expiry_is_24_hours_from_now(self):
        ride = _make_ride_mock(ride_id=1, rider_id=10, driver_id=20, status=RideStatus.IN_PROGRESS)
        db = _db_returning(ride)
        before = _now()
        await create_trip_share_token(ride_id=1, user_id=10, db=db)
        after = _now()
        added_share = db.add.call_args[0][0]
        expected_ttl = timedelta(hours=SHARE_TOKEN_TTL_HOURS)
        assert before + expected_ttl <= added_share.expires_at <= after + expected_ttl + timedelta(seconds=1)

    @pytest.mark.asyncio
    async def test_token_string_is_generated(self):
        ride = _make_ride_mock(ride_id=1, rider_id=10, driver_id=20, status=RideStatus.IN_PROGRESS)
        db = _db_returning(ride)
        await create_trip_share_token(ride_id=1, user_id=10, db=db)
        added_share = db.add.call_args[0][0]
        assert isinstance(added_share.token, str)
        assert len(added_share.token) > 0


# ===========================================================================
# TestGetSharedTrip
# ===========================================================================


class TestGetSharedTrip:
    """Tests for get_shared_trip (async service with mocked DB)."""

    @pytest.mark.asyncio
    async def test_valid_token_returns_ride(self):
        ride = _make_ride_mock(ride_id=1)
        share = _make_share_token_mock(
            token="valid_token",
            ride_id=1,
            expires_at=_now() + timedelta(hours=10),
        )
        db = _db_returning(share, ride)
        result = await get_shared_trip(token="valid_token", db=db)
        assert result is ride

    @pytest.mark.asyncio
    async def test_token_not_found_returns_none(self):
        db = _db_returning(None)
        result = await get_shared_trip(token="bad_token", db=db)
        assert result is None

    @pytest.mark.asyncio
    async def test_expired_token_returns_none(self):
        share = _make_share_token_mock(
            token="expired_token",
            expires_at=_now() - timedelta(hours=1),
        )
        db = _db_returning(share)
        result = await get_shared_trip(token="expired_token", db=db)
        assert result is None

    @pytest.mark.asyncio
    async def test_valid_token_not_expired_returns_ride(self):
        ride = _make_ride_mock(ride_id=5)
        share = _make_share_token_mock(
            token="fresh_token",
            ride_id=5,
            expires_at=_now() + timedelta(minutes=30),
        )
        db = _db_returning(share, ride)
        result = await get_shared_trip(token="fresh_token", db=db)
        assert result is ride

    @pytest.mark.asyncio
    async def test_two_execute_calls_for_valid_token(self):
        ride = _make_ride_mock(ride_id=1)
        share = _make_share_token_mock(expires_at=_now() + timedelta(hours=10))
        db = _db_returning(share, ride)
        await get_shared_trip(token="token", db=db)
        assert db.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_one_execute_call_for_missing_token(self):
        db = _db_returning(None)
        await get_shared_trip(token="missing", db=db)
        assert db.execute.await_count == 1

    @pytest.mark.asyncio
    async def test_one_execute_call_for_expired_token(self):
        share = _make_share_token_mock(expires_at=_now() - timedelta(hours=1))
        db = _db_returning(share)
        await get_shared_trip(token="expired", db=db)
        assert db.execute.await_count == 1


# ===========================================================================
# TestSafetySchemas
# ===========================================================================


class TestSafetySchemas:
    """Pydantic validation tests for safety-related schemas."""

    def test_sos_trigger_request_all_optional(self):
        req = SOSTriggerRequest()
        assert req.ride_id is None
        assert req.latitude is None
        assert req.longitude is None
        assert req.message is None

    def test_sos_trigger_request_with_values(self):
        req = SOSTriggerRequest(
            ride_id=5,
            latitude=37.77,
            longitude=-122.41,
            message="Emergency!",
        )
        assert req.ride_id == 5
        assert req.latitude == 37.77
        assert req.message == "Emergency!"

    def test_sos_alert_response_fields(self):
        now = _now()
        resp = SOSAlertResponse(
            id=1,
            ride_id=5,
            status="active",
            latitude=37.7,
            longitude=-122.4,
            message="Help",
            created_at=now,
        )
        assert resp.id == 1
        assert resp.status == "active"
        assert resp.resolved_at is None

    def test_sos_alert_response_with_resolved_at(self):
        now = _now()
        resp = SOSAlertResponse(
            id=1,
            ride_id=None,
            status="resolved",
            latitude=None,
            longitude=None,
            message=None,
            created_at=now,
            resolved_at=now,
        )
        assert resp.resolved_at == now

    def test_sos_alert_response_from_attributes(self):
        assert SOSAlertResponse.model_config.get("from_attributes") is True

    def test_sos_resolve_request_default_resolution(self):
        req = SOSResolveRequest()
        assert req.resolution == "false_alarm"

    def test_sos_resolve_request_custom_resolution(self):
        req = SOSResolveRequest(resolution="resolved")
        assert req.resolution == "resolved"

    def test_trip_share_request_requires_ride_id(self):
        with pytest.raises(Exception):
            TripShareRequest()

    def test_trip_share_request_with_ride_id(self):
        req = TripShareRequest(ride_id=42)
        assert req.ride_id == 42

    def test_trip_share_response_fields(self):
        now = _now()
        resp = TripShareResponse(
            token="abc123",
            share_url="/api/v1/safety/share/abc123",
            expires_at=now,
        )
        assert resp.token == "abc123"
        assert "abc123" in resp.share_url

    def test_shared_trip_view_required_fields(self):
        now = _now()
        view = SharedTripView(
            ride_id=1,
            status="in_progress",
            pickup_address="123 Main St",
            dropoff_address="456 Oak Ave",
        )
        assert view.ride_id == 1
        assert view.driver_name is None
        assert view.vehicle_info is None

    def test_shared_trip_view_optional_fields(self):
        now = _now()
        view = SharedTripView(
            ride_id=1,
            status="in_progress",
            pickup_address="123 Main St",
            dropoff_address="456 Oak Ave",
            driver_name="John Driver",
            vehicle_info="Blue Toyota Camry (ABC-123)",
            started_at=now,
        )
        assert view.driver_name == "John Driver"
        assert view.started_at == now

    def test_emergency_contact_create_optional_label(self):
        req = EmergencyContactCreate(name="Alice", phone="+1555000")
        assert req.relationship_label is None

    def test_emergency_contact_create_with_label(self):
        req = EmergencyContactCreate(
            name="Bob",
            phone="+1555001",
            relationship_label="sibling",
        )
        assert req.relationship_label == "sibling"

    def test_emergency_contact_create_requires_name(self):
        with pytest.raises(Exception):
            EmergencyContactCreate(phone="+1555000")

    def test_emergency_contact_create_requires_phone(self):
        with pytest.raises(Exception):
            EmergencyContactCreate(name="Alice")

    def test_emergency_contact_response_fields(self):
        now = _now()
        resp = EmergencyContactResponse(
            id=1,
            name="Jane",
            phone="+1555000",
            relationship_label="friend",
            created_at=now,
        )
        assert resp.id == 1
        assert resp.name == "Jane"
        assert resp.relationship_label == "friend"

    def test_emergency_contact_response_from_attributes(self):
        assert EmergencyContactResponse.model_config.get("from_attributes") is True

    def test_emergency_contact_response_null_label(self):
        now = _now()
        resp = EmergencyContactResponse(
            id=2,
            name="Sam",
            phone="+1555111",
            relationship_label=None,
            created_at=now,
        )
        assert resp.relationship_label is None


# ===========================================================================
# TestSafetyModels
# ===========================================================================


class TestSafetyModels:
    """Tests verifying the safety ORM model table structures."""

    def _cols(self, model):
        return {c.name for c in model.__table__.columns}

    def test_sos_alert_table_name(self):
        from app.models.safety import SOSAlert
        assert SOSAlert.__tablename__ == "sos_alerts"

    def test_sos_alert_has_required_columns(self):
        from app.models.safety import SOSAlert
        cols = self._cols(SOSAlert)
        for col in ("id", "user_id", "ride_id", "status", "latitude", "longitude", "message", "created_at", "resolved_at"):
            assert col in cols, f"Missing column: {col}"

    def test_sos_status_enum_values(self):
        assert SOSStatus.ACTIVE.value == "active"
        assert SOSStatus.RESOLVED.value == "resolved"
        assert SOSStatus.FALSE_ALARM.value == "false_alarm"

    def test_trip_share_token_table_name(self):
        from app.models.safety import TripShareToken
        assert TripShareToken.__tablename__ == "trip_share_tokens"

    def test_trip_share_token_has_required_columns(self):
        from app.models.safety import TripShareToken
        cols = self._cols(TripShareToken)
        for col in ("id", "ride_id", "token", "created_by", "expires_at", "created_at"):
            assert col in cols, f"Missing column: {col}"

    def test_emergency_contact_table_name(self):
        from app.models.safety import EmergencyContact
        assert EmergencyContact.__tablename__ == "emergency_contacts"

    def test_emergency_contact_has_required_columns(self):
        from app.models.safety import EmergencyContact
        cols = self._cols(EmergencyContact)
        for col in ("id", "user_id", "name", "phone", "relationship_label", "created_at"):
            assert col in cols, f"Missing column: {col}"

    def test_sos_alert_user_id_indexed(self):
        from app.models.safety import SOSAlert
        col = SOSAlert.__table__.columns["user_id"]
        assert col.index is True

    def test_trip_share_token_is_unique(self):
        from app.models.safety import TripShareToken
        col = TripShareToken.__table__.columns["token"]
        assert col.unique is True
