"""Unit tests for safety API endpoint handlers (SOS, trip sharing, emergency contacts)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.ride import Ride, RideStatus
from app.models.safety import EmergencyContact, SOSAlert, SOSStatus, TripShareToken
from app.models.user import User, UserRole
from app.schemas.safety import (
    EmergencyContactCreate,
    SOSResolveRequest,
    SOSTriggerRequest,
    TripShareRequest,
)


def _make_user(id=10, role=UserRole.RIDER):
    user = MagicMock(spec=User)
    user.id = id
    user.role = role
    user.is_active = True
    return user


def _mock_db():
    db = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _make_alert(
    id=1, ride_id=None, status=SOSStatus.ACTIVE,
    lat=None, lng=None, message=None, resolved_at=None,
):
    alert = MagicMock(spec=SOSAlert)
    alert.id = id
    alert.ride_id = ride_id
    alert.status = status
    alert.latitude = lat
    alert.longitude = lng
    alert.message = message
    alert.created_at = datetime.now(timezone.utc)
    alert.resolved_at = resolved_at
    return alert


def _make_contact(id=1, name="Mom", phone="+15551234567", rel="Mother"):
    contact = MagicMock(spec=EmergencyContact)
    contact.id = id
    contact.name = name
    contact.phone = phone
    contact.relationship_label = rel
    contact.created_at = datetime.now(timezone.utc)
    return contact


# ---- SOS Trigger ----

class TestSOSTriggerEndpoint:
    @pytest.mark.asyncio
    @patch("app.api.v1.safety.notify_admin_sos", new_callable=AsyncMock)
    @patch("app.api.v1.safety.trigger_sos", new_callable=AsyncMock)
    async def test_trigger_sos_success(self, mock_trigger, mock_notify):
        from fastapi import BackgroundTasks
        from app.api.v1.safety import sos_trigger

        alert = _make_alert(lat=40.7, lng=-74.0, message="Help")
        mock_trigger.return_value = alert

        db = _mock_db()
        user = _make_user()
        req = SOSTriggerRequest(latitude=40.7, longitude=-74.0, message="Help")
        bg = BackgroundTasks()

        result = await sos_trigger(req=req, background_tasks=bg, user=user, db=db)

        assert result.status == "active"
        assert result.latitude == 40.7
        assert result.message == "Help"
        db.commit.assert_awaited_once()
        db.refresh.assert_awaited_once()
        mock_notify.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("app.api.v1.safety.notify_admin_sos", new_callable=AsyncMock)
    @patch("app.api.v1.safety.trigger_sos", new_callable=AsyncMock)
    async def test_trigger_sos_with_ride(self, mock_trigger, mock_notify):
        from fastapi import BackgroundTasks
        from app.api.v1.safety import sos_trigger

        alert = _make_alert(ride_id=5)
        mock_trigger.return_value = alert

        db = _mock_db()
        user = _make_user()
        req = SOSTriggerRequest(ride_id=5)
        bg = BackgroundTasks()

        result = await sos_trigger(req=req, background_tasks=bg, user=user, db=db)
        assert result.ride_id == 5

    @pytest.mark.asyncio
    @patch("app.api.v1.safety.notify_admin_sos", new_callable=AsyncMock)
    @patch("app.api.v1.safety.trigger_sos", new_callable=AsyncMock)
    async def test_trigger_sos_ride_not_found(self, mock_trigger, mock_notify):
        from fastapi import BackgroundTasks
        from app.api.v1.safety import sos_trigger

        mock_trigger.side_effect = ValueError("Ride not found")

        db = _mock_db()
        user = _make_user()
        req = SOSTriggerRequest(ride_id=999)
        bg = BackgroundTasks()

        with pytest.raises(HTTPException) as exc:
            await sos_trigger(req=req, background_tasks=bg, user=user, db=db)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    @patch("app.api.v1.safety.notify_admin_sos", new_callable=AsyncMock)
    @patch("app.api.v1.safety.trigger_sos", new_callable=AsyncMock)
    async def test_trigger_sos_not_participant(self, mock_trigger, mock_notify):
        from fastapi import BackgroundTasks
        from app.api.v1.safety import sos_trigger

        mock_trigger.side_effect = PermissionError("Not a participant in this ride")

        db = _mock_db()
        user = _make_user()
        req = SOSTriggerRequest(ride_id=1)
        bg = BackgroundTasks()

        with pytest.raises(HTTPException) as exc:
            await sos_trigger(req=req, background_tasks=bg, user=user, db=db)
        assert exc.value.status_code == 403


# ---- SOS Resolve ----

class TestSOSResolveEndpoint:
    @pytest.mark.asyncio
    @patch("app.api.v1.safety.resolve_sos", new_callable=AsyncMock)
    async def test_resolve_false_alarm(self, mock_resolve):
        from app.api.v1.safety import sos_resolve

        alert = _make_alert(status=SOSStatus.FALSE_ALARM, resolved_at=datetime.now(timezone.utc))
        mock_resolve.return_value = alert

        db = _mock_db()
        user = _make_user()
        req = SOSResolveRequest(resolution="false_alarm")

        result = await sos_resolve(alert_id=1, req=req, user=user, db=db)
        assert result.status == "false_alarm"
        assert result.resolved_at is not None

    @pytest.mark.asyncio
    @patch("app.api.v1.safety.resolve_sos", new_callable=AsyncMock)
    async def test_resolve_not_found(self, mock_resolve):
        from app.api.v1.safety import sos_resolve

        mock_resolve.side_effect = ValueError("Alert not found")

        db = _mock_db()
        user = _make_user()
        req = SOSResolveRequest()

        with pytest.raises(HTTPException) as exc:
            await sos_resolve(alert_id=999, req=req, user=user, db=db)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    @patch("app.api.v1.safety.resolve_sos", new_callable=AsyncMock)
    async def test_resolve_wrong_user(self, mock_resolve):
        from app.api.v1.safety import sos_resolve

        mock_resolve.side_effect = PermissionError("Not authorized")

        db = _mock_db()
        user = _make_user()
        req = SOSResolveRequest()

        with pytest.raises(HTTPException) as exc:
            await sos_resolve(alert_id=1, req=req, user=user, db=db)
        assert exc.value.status_code == 403


# ---- SOS Active ----

class TestSOSActiveEndpoint:
    @pytest.mark.asyncio
    @patch("app.api.v1.safety.get_active_alerts", new_callable=AsyncMock)
    async def test_get_active_alerts(self, mock_alerts):
        from app.api.v1.safety import sos_active

        mock_alerts.return_value = [_make_alert(), _make_alert(id=2)]

        db = _mock_db()
        user = _make_user()

        result = await sos_active(user=user, db=db)
        assert len(result) == 2

    @pytest.mark.asyncio
    @patch("app.api.v1.safety.get_active_alerts", new_callable=AsyncMock)
    async def test_get_active_alerts_empty(self, mock_alerts):
        from app.api.v1.safety import sos_active

        mock_alerts.return_value = []

        db = _mock_db()
        user = _make_user()

        result = await sos_active(user=user, db=db)
        assert result == []


# ---- Trip Sharing ----

class TestTripShareEndpoint:
    @pytest.mark.asyncio
    @patch("app.api.v1.safety.create_trip_share_token", new_callable=AsyncMock)
    async def test_create_share(self, mock_share):
        from app.api.v1.safety import share_trip

        share = MagicMock(spec=TripShareToken)
        share.token = "abc123token"
        share.expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
        mock_share.return_value = share

        db = _mock_db()
        user = _make_user()
        req = TripShareRequest(ride_id=1)

        result = await share_trip(req=req, user=user, db=db)
        assert result.token == "abc123token"
        assert "/safety/share/abc123token" in result.share_url
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("app.api.v1.safety.create_trip_share_token", new_callable=AsyncMock)
    async def test_create_share_ride_not_found(self, mock_share):
        from app.api.v1.safety import share_trip

        mock_share.side_effect = ValueError("Ride not found")

        db = _mock_db()
        user = _make_user()
        req = TripShareRequest(ride_id=999)

        with pytest.raises(HTTPException) as exc:
            await share_trip(req=req, user=user, db=db)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    @patch("app.api.v1.safety.create_trip_share_token", new_callable=AsyncMock)
    async def test_create_share_not_participant(self, mock_share):
        from app.api.v1.safety import share_trip

        mock_share.side_effect = PermissionError("Not a participant")

        db = _mock_db()
        user = _make_user()
        req = TripShareRequest(ride_id=1)

        with pytest.raises(HTTPException) as exc:
            await share_trip(req=req, user=user, db=db)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    @patch("app.api.v1.safety.create_trip_share_token", new_callable=AsyncMock)
    async def test_create_share_finished_ride(self, mock_share):
        from app.api.v1.safety import share_trip

        mock_share.side_effect = ValueError("Cannot share a finished ride")

        db = _mock_db()
        user = _make_user()
        req = TripShareRequest(ride_id=1)

        with pytest.raises(HTTPException) as exc:
            await share_trip(req=req, user=user, db=db)
        assert exc.value.status_code == 400


class TestViewSharedTripEndpoint:
    @pytest.mark.asyncio
    @patch("app.api.v1.safety.get_shared_trip", new_callable=AsyncMock)
    async def test_view_valid_share(self, mock_get):
        from app.api.v1.safety import view_shared_trip

        ride = MagicMock(spec=Ride)
        ride.id = 1
        ride.status = RideStatus.IN_PROGRESS
        ride.pickup_address = "123 Main St"
        ride.dropoff_address = "456 Oak Ave"
        ride.started_at = datetime.now(timezone.utc)
        ride.driver = None
        mock_get.return_value = ride

        db = _mock_db()

        result = await view_shared_trip(token="valid-token", db=db)
        assert result.ride_id == 1
        assert result.status == "in_progress"
        assert result.pickup_address == "123 Main St"
        assert result.driver_name is None

    @pytest.mark.asyncio
    @patch("app.api.v1.safety.get_shared_trip", new_callable=AsyncMock)
    async def test_view_share_with_driver(self, mock_get):
        from app.api.v1.safety import view_shared_trip

        driver = MagicMock()
        driver.name = "John Driver"

        ride = MagicMock(spec=Ride)
        ride.id = 1
        ride.status = RideStatus.IN_PROGRESS
        ride.pickup_address = "123 Main St"
        ride.dropoff_address = "456 Oak Ave"
        ride.started_at = datetime.now(timezone.utc)
        ride.driver = driver
        # No driver_profiles attribute on the mock
        del ride.driver.driver_profiles
        mock_get.return_value = ride

        db = _mock_db()

        result = await view_shared_trip(token="valid-token", db=db)
        assert result.driver_name == "John Driver"
        assert result.vehicle_info is None

    @pytest.mark.asyncio
    @patch("app.api.v1.safety.get_shared_trip", new_callable=AsyncMock)
    async def test_view_invalid_share(self, mock_get):
        from app.api.v1.safety import view_shared_trip

        mock_get.return_value = None

        db = _mock_db()

        with pytest.raises(HTTPException) as exc:
            await view_shared_trip(token="invalid-token", db=db)
        assert exc.value.status_code == 404


# ---- Emergency Contacts ----

class TestContactEndpoints:
    @pytest.mark.asyncio
    @patch("app.api.v1.safety.list_emergency_contacts", new_callable=AsyncMock)
    async def test_list_contacts(self, mock_list):
        from app.api.v1.safety import get_contacts

        mock_list.return_value = [_make_contact(), _make_contact(id=2, name="Dad", phone="+15559876543")]

        db = _mock_db()
        user = _make_user()

        result = await get_contacts(user=user, db=db)
        assert len(result) == 2
        assert result[0].name == "Mom"

    @pytest.mark.asyncio
    @patch("app.api.v1.safety.list_emergency_contacts", new_callable=AsyncMock)
    async def test_list_contacts_empty(self, mock_list):
        from app.api.v1.safety import get_contacts

        mock_list.return_value = []

        db = _mock_db()
        user = _make_user()

        result = await get_contacts(user=user, db=db)
        assert result == []

    @pytest.mark.asyncio
    @patch("app.api.v1.safety.add_emergency_contact", new_callable=AsyncMock)
    async def test_create_contact(self, mock_add):
        from app.api.v1.safety import create_contact

        mock_add.return_value = _make_contact()

        db = _mock_db()
        user = _make_user()
        req = EmergencyContactCreate(name="Mom", phone="+15551234567", relationship_label="Mother")

        result = await create_contact(req=req, user=user, db=db)
        assert result.name == "Mom"
        assert result.phone == "+15551234567"
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("app.api.v1.safety.add_emergency_contact", new_callable=AsyncMock)
    async def test_create_contact_no_relationship(self, mock_add):
        from app.api.v1.safety import create_contact

        contact = _make_contact(rel=None)
        mock_add.return_value = contact

        db = _mock_db()
        user = _make_user()
        req = EmergencyContactCreate(name="Friend", phone="+15559999999")

        result = await create_contact(req=req, user=user, db=db)
        assert result.relationship_label is None

    @pytest.mark.asyncio
    @patch("app.api.v1.safety.delete_emergency_contact", new_callable=AsyncMock)
    async def test_delete_contact_success(self, mock_del):
        from app.api.v1.safety import remove_contact

        mock_del.return_value = True

        db = _mock_db()
        user = _make_user()

        # Should not raise
        await remove_contact(contact_id=1, user=user, db=db)
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("app.api.v1.safety.delete_emergency_contact", new_callable=AsyncMock)
    async def test_delete_contact_not_found(self, mock_del):
        from app.api.v1.safety import remove_contact

        mock_del.return_value = False

        db = _mock_db()
        user = _make_user()

        with pytest.raises(HTTPException) as exc:
            await remove_contact(contact_id=999, user=user, db=db)
        assert exc.value.status_code == 404
