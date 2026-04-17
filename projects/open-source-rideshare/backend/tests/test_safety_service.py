from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.ride import Ride, RideStatus
from app.models.safety import EmergencyContact, SOSAlert, SOSStatus, TripShareToken
from app.services.safety import (
    SHARE_TOKEN_BYTES,
    add_emergency_contact,
    create_trip_share_token,
    delete_emergency_contact,
    get_active_alerts,
    get_shared_trip,
    get_shared_trip_detail,
    list_emergency_contacts,
    list_trip_share_tokens,
    resolve_sos,
    revoke_trip_share_token,
    trigger_sos,
)


def _mock_db():
    """Create a mock async session with common patterns."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.delete = AsyncMock()
    return db


def _mock_ride(ride_id=1, rider_id=10, driver_id=20, status=RideStatus.IN_PROGRESS):
    ride = MagicMock(spec=Ride)
    ride.id = ride_id
    ride.rider_id = rider_id
    ride.driver_id = driver_id
    ride.status = status
    ride.pickup_address = "123 Main St"
    ride.dropoff_address = "456 Oak Ave"
    ride.started_at = datetime.now(timezone.utc)
    return ride


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _scalars_result(items):
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = items
    result.scalars.return_value = scalars
    return result


# ---- SOS Trigger ----

class TestTriggerSOS:
    @pytest.mark.asyncio
    async def test_trigger_without_ride(self):
        db = _mock_db()
        alert = await trigger_sos(user_id=10, db=db)
        # First add call is the SOS alert; subsequent calls may be notification logs
        added = db.add.call_args_list[0][0][0]
        assert added.user_id == 10
        assert added.ride_id is None
        assert added.status == SOSStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_trigger_with_ride_as_rider(self):
        db = _mock_db()
        ride = _mock_ride(ride_id=5, rider_id=10)
        db.execute = AsyncMock(return_value=_scalar_result(ride))

        alert = await trigger_sos(user_id=10, db=db, ride_id=5, latitude=40.7, longitude=-74.0)
        # First add call is the SOS alert
        added = db.add.call_args_list[0][0][0]
        assert added.ride_id == 5
        assert added.latitude == 40.7
        assert added.longitude == -74.0

    @pytest.mark.asyncio
    async def test_trigger_with_ride_as_driver(self):
        db = _mock_db()
        ride = _mock_ride(ride_id=5, rider_id=10, driver_id=20)
        db.execute = AsyncMock(return_value=_scalar_result(ride))

        alert = await trigger_sos(user_id=20, db=db, ride_id=5)
        # First add call is the SOS alert
        added = db.add.call_args_list[0][0][0]
        assert isinstance(added, SOSAlert)

    @pytest.mark.asyncio
    async def test_trigger_ride_not_found(self):
        db = _mock_db()
        db.execute = AsyncMock(return_value=_scalar_result(None))

        with pytest.raises(ValueError, match="Ride not found"):
            await trigger_sos(user_id=10, db=db, ride_id=999)

    @pytest.mark.asyncio
    async def test_trigger_not_participant(self):
        db = _mock_db()
        ride = _mock_ride(rider_id=10, driver_id=20)
        db.execute = AsyncMock(return_value=_scalar_result(ride))

        with pytest.raises(PermissionError, match="Not a participant"):
            await trigger_sos(user_id=99, db=db, ride_id=1)

    @pytest.mark.asyncio
    async def test_trigger_with_message(self):
        db = _mock_db()
        alert = await trigger_sos(user_id=10, db=db, message="I feel unsafe")
        # First add call is the SOS alert
        added = db.add.call_args_list[0][0][0]
        assert added.message == "I feel unsafe"


# ---- SOS Resolve ----

class TestResolveSOS:
    @pytest.mark.asyncio
    async def test_resolve_false_alarm(self):
        db = _mock_db()
        alert = MagicMock(spec=SOSAlert)
        alert.id = 1
        alert.user_id = 10
        alert.status = SOSStatus.ACTIVE
        db.execute = AsyncMock(return_value=_scalar_result(alert))

        result = await resolve_sos(1, user_id=10, db=db, resolution="false_alarm")
        assert alert.status == SOSStatus.FALSE_ALARM
        assert alert.resolved_at is not None

    @pytest.mark.asyncio
    async def test_resolve_resolved(self):
        db = _mock_db()
        alert = MagicMock(spec=SOSAlert)
        alert.id = 1
        alert.user_id = 10
        alert.status = SOSStatus.ACTIVE
        db.execute = AsyncMock(return_value=_scalar_result(alert))

        result = await resolve_sos(1, user_id=10, db=db, resolution="resolved")
        assert alert.status == SOSStatus.RESOLVED

    @pytest.mark.asyncio
    async def test_resolve_not_found(self):
        db = _mock_db()
        db.execute = AsyncMock(return_value=_scalar_result(None))

        with pytest.raises(ValueError, match="Alert not found"):
            await resolve_sos(999, user_id=10, db=db)

    @pytest.mark.asyncio
    async def test_resolve_wrong_user(self):
        db = _mock_db()
        alert = MagicMock(spec=SOSAlert)
        alert.user_id = 10
        alert.status = SOSStatus.ACTIVE
        db.execute = AsyncMock(return_value=_scalar_result(alert))

        with pytest.raises(PermissionError, match="Not authorized"):
            await resolve_sos(1, user_id=99, db=db)

    @pytest.mark.asyncio
    async def test_resolve_already_resolved(self):
        db = _mock_db()
        alert = MagicMock(spec=SOSAlert)
        alert.user_id = 10
        alert.status = SOSStatus.RESOLVED
        db.execute = AsyncMock(return_value=_scalar_result(alert))

        with pytest.raises(ValueError, match="not active"):
            await resolve_sos(1, user_id=10, db=db)


# ---- Active Alerts ----

class TestGetActiveAlerts:
    @pytest.mark.asyncio
    async def test_returns_active_alerts(self):
        db = _mock_db()
        alerts = [MagicMock(spec=SOSAlert), MagicMock(spec=SOSAlert)]
        db.execute = AsyncMock(return_value=_scalars_result(alerts))

        result = await get_active_alerts(user_id=10, db=db)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_returns_empty_when_none(self):
        db = _mock_db()
        db.execute = AsyncMock(return_value=_scalars_result([]))

        result = await get_active_alerts(user_id=10, db=db)
        assert result == []


# ---- Trip Share Token ----

class TestCreateTripShareToken:
    @pytest.mark.asyncio
    async def test_create_share_as_rider(self):
        db = _mock_db()
        ride = _mock_ride(rider_id=10, status=RideStatus.IN_PROGRESS)
        db.execute = AsyncMock(return_value=_scalar_result(ride))

        share = await create_trip_share_token(ride_id=1, user_id=10, db=db)
        added = db.add.call_args[0][0]
        assert added.ride_id == 1
        assert added.created_by == 10
        assert len(added.token) > 0
        assert added.expires_at > datetime.now(timezone.utc)

    @pytest.mark.asyncio
    async def test_create_share_as_driver(self):
        db = _mock_db()
        ride = _mock_ride(driver_id=20, status=RideStatus.IN_PROGRESS)
        db.execute = AsyncMock(return_value=_scalar_result(ride))

        share = await create_trip_share_token(ride_id=1, user_id=20, db=db)
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_share_ride_not_found(self):
        db = _mock_db()
        db.execute = AsyncMock(return_value=_scalar_result(None))

        with pytest.raises(ValueError, match="Ride not found"):
            await create_trip_share_token(ride_id=999, user_id=10, db=db)

    @pytest.mark.asyncio
    async def test_share_not_participant(self):
        db = _mock_db()
        ride = _mock_ride(rider_id=10, driver_id=20)
        db.execute = AsyncMock(return_value=_scalar_result(ride))

        with pytest.raises(PermissionError, match="Not a participant"):
            await create_trip_share_token(ride_id=1, user_id=99, db=db)

    @pytest.mark.asyncio
    async def test_share_completed_ride(self):
        db = _mock_db()
        ride = _mock_ride(status=RideStatus.COMPLETED)
        db.execute = AsyncMock(return_value=_scalar_result(ride))

        with pytest.raises(ValueError, match="Cannot share a finished ride"):
            await create_trip_share_token(ride_id=1, user_id=10, db=db)

    @pytest.mark.asyncio
    async def test_share_cancelled_ride(self):
        db = _mock_db()
        ride = _mock_ride(status=RideStatus.CANCELLED)
        db.execute = AsyncMock(return_value=_scalar_result(ride))

        with pytest.raises(ValueError, match="Cannot share a finished ride"):
            await create_trip_share_token(ride_id=1, user_id=10, db=db)


# ---- Get Shared Trip ----

class TestGetSharedTrip:
    @pytest.mark.asyncio
    async def test_valid_token(self):
        db = _mock_db()
        share = MagicMock(spec=TripShareToken)
        share.ride_id = 1
        share.expires_at = datetime.now(timezone.utc) + timedelta(hours=12)

        ride = _mock_ride(ride_id=1)

        db.execute = AsyncMock(
            side_effect=[_scalar_result(share), _scalar_result(ride)]
        )

        result = await get_shared_trip("valid-token", db)
        assert result is not None
        assert result.id == 1

    @pytest.mark.asyncio
    async def test_invalid_token(self):
        db = _mock_db()
        db.execute = AsyncMock(return_value=_scalar_result(None))

        result = await get_shared_trip("invalid-token", db)
        assert result is None

    @pytest.mark.asyncio
    async def test_expired_token(self):
        db = _mock_db()
        share = MagicMock(spec=TripShareToken)
        share.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.execute = AsyncMock(return_value=_scalar_result(share))

        result = await get_shared_trip("expired-token", db)
        assert result is None


# ---- Emergency Contacts ----

class TestEmergencyContacts:
    @pytest.mark.asyncio
    async def test_add_contact(self):
        db = _mock_db()
        contact = await add_emergency_contact(
            user_id=10, name="Mom", phone="+15551234567", db=db,
            relationship_label="Mother",
        )
        added = db.add.call_args[0][0]
        assert added.user_id == 10
        assert added.name == "Mom"
        assert added.phone == "+15551234567"
        assert added.relationship_label == "Mother"

    @pytest.mark.asyncio
    async def test_add_contact_no_relationship(self):
        db = _mock_db()
        contact = await add_emergency_contact(
            user_id=10, name="Friend", phone="+15559876543", db=db,
        )
        added = db.add.call_args[0][0]
        assert added.relationship_label is None

    @pytest.mark.asyncio
    async def test_list_contacts(self):
        db = _mock_db()
        contacts = [MagicMock(spec=EmergencyContact), MagicMock(spec=EmergencyContact)]
        db.execute = AsyncMock(return_value=_scalars_result(contacts))

        result = await list_emergency_contacts(user_id=10, db=db)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_list_contacts_empty(self):
        db = _mock_db()
        db.execute = AsyncMock(return_value=_scalars_result([]))

        result = await list_emergency_contacts(user_id=10, db=db)
        assert result == []

    @pytest.mark.asyncio
    async def test_delete_contact_success(self):
        db = _mock_db()
        contact = MagicMock(spec=EmergencyContact)
        db.execute = AsyncMock(return_value=_scalar_result(contact))

        result = await delete_emergency_contact(contact_id=1, user_id=10, db=db)
        assert result is True
        db.delete.assert_awaited_once_with(contact)

    @pytest.mark.asyncio
    async def test_delete_contact_not_found(self):
        db = _mock_db()
        db.execute = AsyncMock(return_value=_scalar_result(None))

        result = await delete_emergency_contact(contact_id=999, user_id=10, db=db)
        assert result is False
        db.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_delete_contact_wrong_user(self):
        db = _mock_db()
        # The query filters by user_id, so wrong user returns None
        db.execute = AsyncMock(return_value=_scalar_result(None))

        result = await delete_emergency_contact(contact_id=1, user_id=99, db=db)
        assert result is False


# ---- get_shared_trip_detail ----

class TestGetSharedTripDetail:
    def _make_share(self, ride_id=1, hours_until_expiry=12):
        share = MagicMock(spec=TripShareToken)
        share.ride_id = ride_id
        share.expires_at = datetime.now(timezone.utc) + timedelta(hours=hours_until_expiry)
        return share

    @pytest.mark.asyncio
    async def test_returns_detail_without_driver_location(self):
        db = _mock_db()
        share = self._make_share()
        ride = _mock_ride(ride_id=1, driver_id=None)

        # Make ride.driver_id return None so no location query is made
        ride.driver_id = None

        # First execute: token lookup; second: ride lookup
        db.execute = AsyncMock(side_effect=[
            _scalar_result(share),
            _scalar_result(ride),
        ])

        detail = await get_shared_trip_detail("valid-token", db)
        assert detail is not None
        assert detail["ride"] is ride
        assert detail["driver_lat"] is None
        assert detail["driver_lng"] is None
        assert detail["driver_location_updated_at"] is None

    @pytest.mark.asyncio
    async def test_returns_driver_location_when_available(self):
        db = _mock_db()
        share = self._make_share()
        ride = _mock_ride(ride_id=1, driver_id=20)

        loc_row = MagicMock()
        loc_row.lat = 40.7128
        loc_row.lng = -74.0060
        loc_row.updated_at = datetime.now(timezone.utc)

        loc_result = MagicMock()
        loc_result.one_or_none.return_value = loc_row

        db.execute = AsyncMock(side_effect=[
            _scalar_result(share),
            _scalar_result(ride),
            loc_result,
        ])

        detail = await get_shared_trip_detail("valid-token", db)
        assert detail is not None
        assert detail["driver_lat"] == 40.7128
        assert detail["driver_lng"] == -74.0060
        assert detail["driver_location_updated_at"] is not None

    @pytest.mark.asyncio
    async def test_driver_location_none_when_not_submitted(self):
        db = _mock_db()
        share = self._make_share()
        ride = _mock_ride(ride_id=1, driver_id=20)

        loc_row = MagicMock()
        loc_row.lat = None  # driver exists but never submitted location
        loc_row.lng = None

        loc_result = MagicMock()
        loc_result.one_or_none.return_value = loc_row

        db.execute = AsyncMock(side_effect=[
            _scalar_result(share),
            _scalar_result(ride),
            loc_result,
        ])

        detail = await get_shared_trip_detail("valid-token", db)
        assert detail["driver_lat"] is None
        assert detail["driver_lng"] is None

    @pytest.mark.asyncio
    async def test_invalid_token_returns_none(self):
        db = _mock_db()
        db.execute = AsyncMock(return_value=_scalar_result(None))

        detail = await get_shared_trip_detail("bad-token", db)
        assert detail is None

    @pytest.mark.asyncio
    async def test_expired_token_returns_none(self):
        db = _mock_db()
        share = self._make_share(hours_until_expiry=-1)  # already expired
        db.execute = AsyncMock(return_value=_scalar_result(share))

        detail = await get_shared_trip_detail("expired-token", db)
        assert detail is None


# ---- revoke_trip_share_token ----

class TestRevokeTripShareToken:
    @pytest.mark.asyncio
    async def test_revoke_own_token(self):
        db = _mock_db()
        share = MagicMock(spec=TripShareToken)
        share.created_by = 10
        db.execute = AsyncMock(return_value=_scalar_result(share))

        result = await revoke_trip_share_token("some-token", user_id=10, db=db)
        assert result is True
        db.delete.assert_awaited_once_with(share)
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_revoke_not_found(self):
        db = _mock_db()
        db.execute = AsyncMock(return_value=_scalar_result(None))

        result = await revoke_trip_share_token("missing-token", user_id=10, db=db)
        assert result is False
        db.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_revoke_wrong_user(self):
        db = _mock_db()
        share = MagicMock(spec=TripShareToken)
        share.created_by = 10  # belongs to user 10
        db.execute = AsyncMock(return_value=_scalar_result(share))

        with pytest.raises(PermissionError, match="Not authorized"):
            await revoke_trip_share_token("some-token", user_id=99, db=db)
        db.delete.assert_not_awaited()


# ---- list_trip_share_tokens ----

class TestListTripShareTokens:
    @pytest.mark.asyncio
    async def test_returns_active_tokens(self):
        db = _mock_db()
        tokens = [MagicMock(spec=TripShareToken), MagicMock(spec=TripShareToken)]
        db.execute = AsyncMock(return_value=_scalars_result(tokens))

        result = await list_trip_share_tokens(user_id=10, db=db)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_returns_empty_when_none(self):
        db = _mock_db()
        db.execute = AsyncMock(return_value=_scalars_result([]))

        result = await list_trip_share_tokens(user_id=10, db=db)
        assert result == []
