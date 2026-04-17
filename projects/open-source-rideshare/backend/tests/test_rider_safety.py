"""Tests for rider emergency safety features.

POST   /riders/me/panic
GET    /riders/me/panic/{alert_id}
DELETE /riders/me/panic/{alert_id}
GET    /admin/panic-alerts
POST   /admin/panic-alerts/{alert_id}/resolve

POST   /riders/me/trusted-contacts
GET    /riders/me/trusted-contacts
PUT    /riders/me/trusted-contacts/{contact_id}
DELETE /riders/me/trusted-contacts/{contact_id}
GET    /riders/me/trusted-contacts/{contact_id}/notification-log

Coverage
--------
Schemas
  - PanicAlertStatus: ACTIVE, RESOLVED, FALSE_ALARM
  - TrustedContactNotificationType: TRIP_START, TRIP_END, PANIC_ALERT
  - TrustedContactDeliveryStatus: SENT, DELIVERED, FAILED
  - TriggerPanicRequest: valid with and without location
  - PanicAlertResponse: all fields present
  - TrustedContactCreate: valid, name too short, phone too short
  - TrustedContactUpdate: all fields optional
  - TrustedContactNotificationLogResponse: contact_id and items

Service: trigger_panic
  - creates alert with ACTIVE status
  - stores ride_id, rider_id, driver_id correctly
  - stores optional lat/lng
  - assigns unique UUID ids
  - raises ValueError if ACTIVE alert already exists for ride
  - second alert on different ride succeeds

Service: get_panic_alert
  - returns alert for correct owner
  - returns None for wrong owner (404 guard)
  - returns None for nonexistent id

Service: cancel_panic_alert
  - within 30s -> FALSE_ALARM
  - after 30s -> RESOLVED
  - raises PermissionError for wrong owner
  - raises ValueError if alert not ACTIVE

Service: admin_list_active_panic_alerts
  - empty when no alerts
  - only returns ACTIVE alerts (not RESOLVED/FALSE_ALARM)
  - sorted oldest-first
  - pagination skip and limit

Service: admin_resolve_panic_alert
  - sets RESOLVED status
  - stores admin_id as resolved_by
  - stores resolution_notes
  - raises KeyError for nonexistent alert
  - raises ValueError if already resolved

Service: add_trusted_contact
  - creates contact with correct fields
  - defaults: notify_on_trip_start/end/panic all True, is_active True
  - raises ValueError when 4th active contact would be added
  - deactivated contacts do not count toward the limit

Service: list_trusted_contacts
  - returns empty list for new rider
  - returns all contacts (active and inactive), ordered by created_at

Service: get_trusted_contact
  - returns contact for correct owner
  - returns None for wrong owner

Service: update_trusted_contact
  - updates only provided fields
  - raises PermissionError for wrong owner

Service: deactivate_trusted_contact
  - sets is_active=False
  - raises PermissionError for wrong owner

Service: get_notification_log
  - empty for new contact
  - returns up to 30, most recent first
  - raises PermissionError for wrong owner

Service: send_trusted_contact_notifications
  - TRIP_START notifies contacts with notify_on_trip_start=True
  - PANIC_ALERT notifies contacts with notify_on_panic=True
  - skips contacts with flag=False
  - skips inactive contacts
  - message_preview is populated
  - delivery_status is SENT

Router: post_trigger_panic
  - delegates to service correctly
  - 400 when service raises ValueError (duplicate active alert)

Router: get_panic_alert_endpoint
  - 404 when service returns None

Router: delete_cancel_panic_alert
  - 404 when PermissionError
  - 400 when ValueError

Router: admin_get_active_panic_alerts
  - returns PanicAlertListResponse

Router: admin_post_resolve_panic_alert
  - 404 on KeyError
  - 400 on ValueError

Router: post_add_trusted_contact
  - 400 when max contacts exceeded

Router: put_update_trusted_contact
  - 404 when PermissionError

Router: delete_deactivate_trusted_contact
  - 404 when PermissionError

Router: get_contact_notification_log
  - 404 when PermissionError

End-to-end: panic alert flow
  - trigger -> admin_list shows it -> admin_resolve -> alert resolved

End-to-end: trusted contact limit
  - add 3 contacts succeeds, 4th raises ValueError
"""
from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ValidationError

from app.schemas.rider_safety import (
    AdminResolvePanicRequest,
    PanicAlertListResponse,
    PanicAlertResponse,
    PanicAlertStatus,
    TriggerPanicRequest,
    TrustedContactCreate,
    TrustedContactDeliveryStatus,
    TrustedContactNotificationLogResponse,
    TrustedContactNotificationType,
    TrustedContactResponse,
    TrustedContactUpdate,
)
from app.services.rider_safety import (
    _reset_store,
    add_trusted_contact,
    admin_list_active_panic_alerts,
    admin_resolve_panic_alert,
    cancel_panic_alert,
    deactivate_trusted_contact,
    get_notification_log,
    get_panic_alert,
    get_trusted_contact,
    list_trusted_contacts,
    send_trusted_contact_notifications,
    trigger_panic,
    update_trusted_contact,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


@pytest.fixture(autouse=True)
def reset_safety_store():
    """Reset in-memory stores before each test."""
    _reset_store()
    yield
    _reset_store()


@pytest.fixture
def mock_db():
    return AsyncMock()


async def _make_alert(
    mock_db,
    rider_id: int = 1,
    ride_id: int = 100,
    driver_id: int = 2,
    location_lat: Optional[float] = None,
    location_lng: Optional[float] = None,
) -> dict:
    return await trigger_panic(
        db=mock_db,
        rider_id=rider_id,
        ride_id=ride_id,
        driver_id=driver_id,
        location_lat=location_lat,
        location_lng=location_lng,
    )


async def _make_contact(
    mock_db,
    rider_id: int = 1,
    name: str = "Alice Smith",
    phone: str = "+15551234567",
    email: Optional[str] = None,
    notify_on_trip_start: bool = True,
    notify_on_trip_end: bool = True,
    notify_on_panic: bool = True,
) -> dict:
    return await add_trusted_contact(
        db=mock_db,
        rider_id=rider_id,
        name=name,
        phone=phone,
        email=email,
        notify_on_trip_start=notify_on_trip_start,
        notify_on_trip_end=notify_on_trip_end,
        notify_on_panic=notify_on_panic,
    )


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestPanicAlertStatusEnum:
    def test_all_values_present(self):
        values = {s.value for s in PanicAlertStatus}
        assert "ACTIVE" in values
        assert "RESOLVED" in values
        assert "FALSE_ALARM" in values

    def test_count(self):
        assert len(PanicAlertStatus) == 3


class TestTrustedContactNotificationTypeEnum:
    def test_all_values_present(self):
        values = {t.value for t in TrustedContactNotificationType}
        assert "TRIP_START" in values
        assert "TRIP_END" in values
        assert "PANIC_ALERT" in values

    def test_count(self):
        assert len(TrustedContactNotificationType) == 3


class TestTrustedContactDeliveryStatusEnum:
    def test_all_values_present(self):
        values = {d.value for d in TrustedContactDeliveryStatus}
        assert "SENT" in values
        assert "DELIVERED" in values
        assert "FAILED" in values

    def test_count(self):
        assert len(TrustedContactDeliveryStatus) == 3


class TestTriggerPanicRequest:
    def test_valid_no_location(self):
        req = TriggerPanicRequest()
        assert req.location_lat is None
        assert req.location_lng is None

    def test_valid_with_location(self):
        req = TriggerPanicRequest(location_lat=37.7749, location_lng=-122.4194)
        assert req.location_lat == pytest.approx(37.7749)
        assert req.location_lng == pytest.approx(-122.4194)


class TestTrustedContactCreate:
    def test_valid_minimal(self):
        req = TrustedContactCreate(name="Bob", phone="+15551234567")
        assert req.name == "Bob"
        assert req.notify_on_trip_start is True
        assert req.notify_on_trip_end is True
        assert req.notify_on_panic is True
        assert req.email is None

    def test_valid_full(self):
        req = TrustedContactCreate(
            name="Carol",
            phone="+15557654321",
            email="carol@example.com",
            notify_on_trip_start=False,
            notify_on_trip_end=True,
            notify_on_panic=True,
        )
        assert req.notify_on_trip_start is False
        assert req.email == "carol@example.com"

    def test_name_too_short(self):
        with pytest.raises(ValidationError):
            TrustedContactCreate(name="", phone="+15551234567")

    def test_phone_too_short(self):
        with pytest.raises(ValidationError):
            TrustedContactCreate(name="Bob", phone="123")


class TestTrustedContactUpdate:
    def test_all_fields_optional(self):
        req = TrustedContactUpdate()
        assert req.name is None
        assert req.phone is None
        assert req.email is None
        assert req.notify_on_trip_start is None
        assert req.notify_on_trip_end is None
        assert req.notify_on_panic is None

    def test_partial_update(self):
        req = TrustedContactUpdate(name="New Name", notify_on_panic=False)
        assert req.name == "New Name"
        assert req.notify_on_panic is False
        assert req.phone is None


# ---------------------------------------------------------------------------
# Service: trigger_panic
# ---------------------------------------------------------------------------


class TestTriggerPanic:
    @pytest.mark.asyncio
    async def test_creates_active_alert(self, mock_db):
        alert = await _make_alert(mock_db)
        assert alert["status"] == PanicAlertStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_stores_ids_correctly(self, mock_db):
        alert = await _make_alert(mock_db, rider_id=5, ride_id=200, driver_id=10)
        assert alert["rider_id"] == 5
        assert alert["ride_id"] == 200
        assert alert["driver_id"] == 10

    @pytest.mark.asyncio
    async def test_stores_optional_location(self, mock_db):
        alert = await _make_alert(mock_db, location_lat=37.77, location_lng=-122.41)
        assert alert["location_lat"] == pytest.approx(37.77)
        assert alert["location_lng"] == pytest.approx(-122.41)

    @pytest.mark.asyncio
    async def test_none_location_when_not_provided(self, mock_db):
        alert = await _make_alert(mock_db)
        assert alert["location_lat"] is None
        assert alert["location_lng"] is None

    @pytest.mark.asyncio
    async def test_assigns_unique_ids(self, mock_db):
        a1 = await _make_alert(mock_db, ride_id=101)
        a2 = await _make_alert(mock_db, ride_id=102)
        assert a1["id"] != a2["id"]

    @pytest.mark.asyncio
    async def test_raises_value_error_for_duplicate_active_on_same_ride(self, mock_db):
        await _make_alert(mock_db, ride_id=100)
        with pytest.raises(ValueError, match="active panic alert"):
            await _make_alert(mock_db, ride_id=100)

    @pytest.mark.asyncio
    async def test_second_alert_on_different_ride_succeeds(self, mock_db):
        a1 = await _make_alert(mock_db, ride_id=100)
        a2 = await _make_alert(mock_db, ride_id=101)
        assert a1["ride_id"] == 100
        assert a2["ride_id"] == 101

    @pytest.mark.asyncio
    async def test_triggered_at_set_to_now(self, mock_db):
        before = _utc_now()
        alert = await _make_alert(mock_db)
        after = _utc_now()
        assert before <= alert["triggered_at"] <= after


# ---------------------------------------------------------------------------
# Service: get_panic_alert
# ---------------------------------------------------------------------------


class TestGetPanicAlert:
    @pytest.mark.asyncio
    async def test_returns_alert_for_correct_owner(self, mock_db):
        created = await _make_alert(mock_db, rider_id=1)
        result = await get_panic_alert(mock_db, rider_id=1, alert_id=created["id"])
        assert result is not None
        assert result["id"] == created["id"]

    @pytest.mark.asyncio
    async def test_returns_none_for_wrong_owner(self, mock_db):
        created = await _make_alert(mock_db, rider_id=1)
        result = await get_panic_alert(mock_db, rider_id=2, alert_id=created["id"])
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_nonexistent_id(self, mock_db):
        result = await get_panic_alert(mock_db, rider_id=1, alert_id="nonexistent-uuid")
        assert result is None


# ---------------------------------------------------------------------------
# Service: cancel_panic_alert
# ---------------------------------------------------------------------------


class TestCancelPanicAlert:
    @pytest.mark.asyncio
    async def test_cancel_within_30s_gives_false_alarm(self, mock_db):
        alert = await _make_alert(mock_db, rider_id=1)
        result = await cancel_panic_alert(mock_db, rider_id=1, alert_id=alert["id"])
        assert result["status"] == PanicAlertStatus.FALSE_ALARM

    @pytest.mark.asyncio
    async def test_cancel_after_30s_gives_resolved(self, mock_db):
        alert = await _make_alert(mock_db, rider_id=1)
        # Backdate triggered_at so it appears > 30s ago
        from app.services.rider_safety import _panic_alerts
        _panic_alerts[alert["id"]]["triggered_at"] = _utc_now() - timedelta(seconds=31)

        result = await cancel_panic_alert(mock_db, rider_id=1, alert_id=alert["id"])
        assert result["status"] == PanicAlertStatus.RESOLVED

    @pytest.mark.asyncio
    async def test_resolved_at_set_on_cancel(self, mock_db):
        alert = await _make_alert(mock_db, rider_id=1)
        before = _utc_now()
        result = await cancel_panic_alert(mock_db, rider_id=1, alert_id=alert["id"])
        after = _utc_now()
        assert before <= result["resolved_at"] <= after

    @pytest.mark.asyncio
    async def test_raises_permission_error_for_wrong_owner(self, mock_db):
        alert = await _make_alert(mock_db, rider_id=1)
        with pytest.raises(PermissionError):
            await cancel_panic_alert(mock_db, rider_id=2, alert_id=alert["id"])

    @pytest.mark.asyncio
    async def test_raises_permission_error_for_nonexistent(self, mock_db):
        with pytest.raises(PermissionError):
            await cancel_panic_alert(mock_db, rider_id=1, alert_id="no-such-uuid")

    @pytest.mark.asyncio
    async def test_raises_value_error_if_already_resolved(self, mock_db):
        alert = await _make_alert(mock_db, rider_id=1)
        await cancel_panic_alert(mock_db, rider_id=1, alert_id=alert["id"])
        with pytest.raises(ValueError, match="ACTIVE"):
            await cancel_panic_alert(mock_db, rider_id=1, alert_id=alert["id"])


# ---------------------------------------------------------------------------
# Service: admin_list_active_panic_alerts
# ---------------------------------------------------------------------------


class TestAdminListActivePanicAlerts:
    @pytest.mark.asyncio
    async def test_empty_when_no_alerts(self, mock_db):
        total, items = await admin_list_active_panic_alerts(mock_db)
        assert total == 0
        assert items == []

    @pytest.mark.asyncio
    async def test_only_returns_active_alerts(self, mock_db):
        a1 = await _make_alert(mock_db, ride_id=100)
        a2 = await _make_alert(mock_db, ride_id=101)
        # Cancel a2
        await cancel_panic_alert(mock_db, rider_id=1, alert_id=a2["id"])

        total, items = await admin_list_active_panic_alerts(mock_db)
        assert total == 1
        assert items[0]["id"] == a1["id"]

    @pytest.mark.asyncio
    async def test_sorted_oldest_first(self, mock_db):
        a1 = await _make_alert(mock_db, rider_id=1, ride_id=100)
        a2 = await _make_alert(mock_db, rider_id=2, ride_id=101)
        a3 = await _make_alert(mock_db, rider_id=3, ride_id=102)

        # Backdate a2 to be oldest
        from app.services.rider_safety import _panic_alerts
        _panic_alerts[a2["id"]]["triggered_at"] = _utc_now() - timedelta(minutes=10)
        _panic_alerts[a1["id"]]["triggered_at"] = _utc_now() - timedelta(minutes=5)
        # a3 is newest

        total, items = await admin_list_active_panic_alerts(mock_db)
        assert total == 3
        assert items[0]["id"] == a2["id"]  # oldest
        assert items[1]["id"] == a1["id"]
        assert items[2]["id"] == a3["id"]  # newest

    @pytest.mark.asyncio
    async def test_pagination_skip(self, mock_db):
        for i in range(5):
            await _make_alert(mock_db, rider_id=i + 1, ride_id=200 + i)
        total, items = await admin_list_active_panic_alerts(mock_db, skip=3, limit=10)
        assert total == 5
        assert len(items) == 2

    @pytest.mark.asyncio
    async def test_pagination_limit(self, mock_db):
        for i in range(5):
            await _make_alert(mock_db, rider_id=i + 1, ride_id=200 + i)
        total, items = await admin_list_active_panic_alerts(mock_db, skip=0, limit=2)
        assert total == 5
        assert len(items) == 2


# ---------------------------------------------------------------------------
# Service: admin_resolve_panic_alert
# ---------------------------------------------------------------------------


class TestAdminResolvePanicAlert:
    @pytest.mark.asyncio
    async def test_sets_resolved_status(self, mock_db):
        alert = await _make_alert(mock_db)
        result = await admin_resolve_panic_alert(mock_db, alert["id"], admin_id=99)
        assert result["status"] == PanicAlertStatus.RESOLVED

    @pytest.mark.asyncio
    async def test_stores_admin_id_as_resolved_by(self, mock_db):
        alert = await _make_alert(mock_db)
        result = await admin_resolve_panic_alert(mock_db, alert["id"], admin_id=42)
        assert result["resolved_by"] == 42

    @pytest.mark.asyncio
    async def test_stores_resolution_notes(self, mock_db):
        alert = await _make_alert(mock_db)
        result = await admin_resolve_panic_alert(
            mock_db, alert["id"], admin_id=99, resolution_notes="Police dispatched."
        )
        assert result["resolution_notes"] == "Police dispatched."

    @pytest.mark.asyncio
    async def test_resolved_at_set(self, mock_db):
        alert = await _make_alert(mock_db)
        before = _utc_now()
        result = await admin_resolve_panic_alert(mock_db, alert["id"], admin_id=99)
        after = _utc_now()
        assert before <= result["resolved_at"] <= after

    @pytest.mark.asyncio
    async def test_raises_key_error_for_nonexistent(self, mock_db):
        with pytest.raises(KeyError):
            await admin_resolve_panic_alert(mock_db, "no-such-uuid", admin_id=99)

    @pytest.mark.asyncio
    async def test_raises_value_error_if_already_resolved(self, mock_db):
        alert = await _make_alert(mock_db)
        await admin_resolve_panic_alert(mock_db, alert["id"], admin_id=99)
        with pytest.raises(ValueError, match="ACTIVE"):
            await admin_resolve_panic_alert(mock_db, alert["id"], admin_id=99)


# ---------------------------------------------------------------------------
# Service: add_trusted_contact
# ---------------------------------------------------------------------------


class TestAddTrustedContact:
    @pytest.mark.asyncio
    async def test_creates_contact_with_correct_fields(self, mock_db):
        contact = await _make_contact(mock_db, rider_id=1, name="Alice", phone="+15551111111")
        assert contact["rider_id"] == 1
        assert contact["name"] == "Alice"
        assert contact["phone"] == "+15551111111"
        assert contact["is_active"] is True

    @pytest.mark.asyncio
    async def test_defaults_all_notify_flags_true(self, mock_db):
        contact = await _make_contact(mock_db)
        assert contact["notify_on_trip_start"] is True
        assert contact["notify_on_trip_end"] is True
        assert contact["notify_on_panic"] is True

    @pytest.mark.asyncio
    async def test_stores_email(self, mock_db):
        contact = await _make_contact(mock_db, email="alice@example.com")
        assert contact["email"] == "alice@example.com"

    @pytest.mark.asyncio
    async def test_assigns_unique_ids(self, mock_db):
        c1 = await _make_contact(mock_db, rider_id=1, phone="+15550000001")
        c2 = await _make_contact(mock_db, rider_id=1, phone="+15550000002")
        assert c1["id"] != c2["id"]

    @pytest.mark.asyncio
    async def test_raises_value_error_when_4th_active_contact_added(self, mock_db):
        for i in range(3):
            await _make_contact(mock_db, rider_id=1, phone=f"+1555000000{i}")
        with pytest.raises(ValueError, match="3"):
            await _make_contact(mock_db, rider_id=1, phone="+15550000099")

    @pytest.mark.asyncio
    async def test_deactivated_contacts_do_not_count_toward_limit(self, mock_db):
        c1 = await _make_contact(mock_db, rider_id=1, phone="+15550000001")
        await _make_contact(mock_db, rider_id=1, phone="+15550000002")
        await _make_contact(mock_db, rider_id=1, phone="+15550000003")
        # Deactivate c1 — now only 2 active
        await deactivate_trusted_contact(mock_db, rider_id=1, contact_id=c1["id"])
        # Should succeed now
        c4 = await _make_contact(mock_db, rider_id=1, phone="+15550000004")
        assert c4["is_active"] is True

    @pytest.mark.asyncio
    async def test_different_riders_have_independent_limits(self, mock_db):
        for i in range(3):
            await _make_contact(mock_db, rider_id=1, phone=f"+1555100000{i}")
        # Rider 2 can still add contacts
        contact = await _make_contact(mock_db, rider_id=2, phone="+15552000001")
        assert contact["rider_id"] == 2


# ---------------------------------------------------------------------------
# Service: list_trusted_contacts
# ---------------------------------------------------------------------------


class TestListTrustedContacts:
    @pytest.mark.asyncio
    async def test_empty_for_new_rider(self, mock_db):
        result = await list_trusted_contacts(mock_db, rider_id=99)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_all_contacts_for_rider(self, mock_db):
        await _make_contact(mock_db, rider_id=1, phone="+15550000001")
        await _make_contact(mock_db, rider_id=1, phone="+15550000002")
        result = await list_trusted_contacts(mock_db, rider_id=1)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_includes_inactive_contacts(self, mock_db):
        c = await _make_contact(mock_db, rider_id=1, phone="+15550000001")
        await deactivate_trusted_contact(mock_db, rider_id=1, contact_id=c["id"])
        result = await list_trusted_contacts(mock_db, rider_id=1)
        assert len(result) == 1
        assert result[0]["is_active"] is False

    @pytest.mark.asyncio
    async def test_does_not_return_other_rider_contacts(self, mock_db):
        await _make_contact(mock_db, rider_id=1, phone="+15550000001")
        await _make_contact(mock_db, rider_id=2, phone="+15550000002")
        result = await list_trusted_contacts(mock_db, rider_id=1)
        assert len(result) == 1
        assert result[0]["rider_id"] == 1


# ---------------------------------------------------------------------------
# Service: get_trusted_contact
# ---------------------------------------------------------------------------


class TestGetTrustedContact:
    @pytest.mark.asyncio
    async def test_returns_contact_for_correct_owner(self, mock_db):
        c = await _make_contact(mock_db, rider_id=1)
        result = await get_trusted_contact(mock_db, rider_id=1, contact_id=c["id"])
        assert result is not None
        assert result["id"] == c["id"]

    @pytest.mark.asyncio
    async def test_returns_none_for_wrong_owner(self, mock_db):
        c = await _make_contact(mock_db, rider_id=1)
        result = await get_trusted_contact(mock_db, rider_id=2, contact_id=c["id"])
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_nonexistent_id(self, mock_db):
        result = await get_trusted_contact(mock_db, rider_id=1, contact_id="no-such-uuid")
        assert result is None


# ---------------------------------------------------------------------------
# Service: update_trusted_contact
# ---------------------------------------------------------------------------


class TestUpdateTrustedContact:
    @pytest.mark.asyncio
    async def test_updates_provided_fields(self, mock_db):
        c = await _make_contact(mock_db, rider_id=1, name="Alice")
        result = await update_trusted_contact(
            mock_db, rider_id=1, contact_id=c["id"], name="Alicia"
        )
        assert result["name"] == "Alicia"

    @pytest.mark.asyncio
    async def test_does_not_change_unprovided_fields(self, mock_db):
        c = await _make_contact(mock_db, rider_id=1, phone="+15551111111")
        result = await update_trusted_contact(
            mock_db, rider_id=1, contact_id=c["id"], name="New Name"
        )
        assert result["phone"] == "+15551111111"

    @pytest.mark.asyncio
    async def test_updates_notify_flags(self, mock_db):
        c = await _make_contact(mock_db, rider_id=1)
        result = await update_trusted_contact(
            mock_db, rider_id=1, contact_id=c["id"], notify_on_panic=False
        )
        assert result["notify_on_panic"] is False
        assert result["notify_on_trip_start"] is True  # unchanged

    @pytest.mark.asyncio
    async def test_raises_permission_error_for_wrong_owner(self, mock_db):
        c = await _make_contact(mock_db, rider_id=1)
        with pytest.raises(PermissionError):
            await update_trusted_contact(
                mock_db, rider_id=2, contact_id=c["id"], name="Hacker"
            )

    @pytest.mark.asyncio
    async def test_raises_permission_error_for_nonexistent(self, mock_db):
        with pytest.raises(PermissionError):
            await update_trusted_contact(
                mock_db, rider_id=1, contact_id="no-such-uuid", name="Hacker"
            )


# ---------------------------------------------------------------------------
# Service: deactivate_trusted_contact
# ---------------------------------------------------------------------------


class TestDeactivateTrustedContact:
    @pytest.mark.asyncio
    async def test_sets_is_active_false(self, mock_db):
        c = await _make_contact(mock_db, rider_id=1)
        result = await deactivate_trusted_contact(mock_db, rider_id=1, contact_id=c["id"])
        assert result["is_active"] is False

    @pytest.mark.asyncio
    async def test_raises_permission_error_for_wrong_owner(self, mock_db):
        c = await _make_contact(mock_db, rider_id=1)
        with pytest.raises(PermissionError):
            await deactivate_trusted_contact(mock_db, rider_id=2, contact_id=c["id"])

    @pytest.mark.asyncio
    async def test_raises_permission_error_for_nonexistent(self, mock_db):
        with pytest.raises(PermissionError):
            await deactivate_trusted_contact(mock_db, rider_id=1, contact_id="no-such-uuid")


# ---------------------------------------------------------------------------
# Service: get_notification_log
# ---------------------------------------------------------------------------


class TestGetNotificationLog:
    @pytest.mark.asyncio
    async def test_empty_for_new_contact(self, mock_db):
        c = await _make_contact(mock_db, rider_id=1)
        result = await get_notification_log(mock_db, rider_id=1, contact_id=c["id"])
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_notifications_most_recent_first(self, mock_db):
        c = await _make_contact(mock_db, rider_id=1)
        await send_trusted_contact_notifications(
            mock_db, ride_id=10, rider_id=1,
            notification_type=TrustedContactNotificationType.TRIP_START,
        )
        await send_trusted_contact_notifications(
            mock_db, ride_id=11, rider_id=1,
            notification_type=TrustedContactNotificationType.TRIP_END,
        )
        result = await get_notification_log(mock_db, rider_id=1, contact_id=c["id"])
        assert len(result) == 2
        assert result[0]["sent_at"] >= result[1]["sent_at"]

    @pytest.mark.asyncio
    async def test_limit_applies(self, mock_db):
        c = await _make_contact(mock_db, rider_id=1)
        for i in range(35):
            await send_trusted_contact_notifications(
                mock_db, ride_id=10 + i, rider_id=1,
                notification_type=TrustedContactNotificationType.TRIP_START,
            )
        result = await get_notification_log(mock_db, rider_id=1, contact_id=c["id"], limit=30)
        assert len(result) == 30

    @pytest.mark.asyncio
    async def test_raises_permission_error_for_wrong_owner(self, mock_db):
        c = await _make_contact(mock_db, rider_id=1)
        with pytest.raises(PermissionError):
            await get_notification_log(mock_db, rider_id=2, contact_id=c["id"])

    @pytest.mark.asyncio
    async def test_raises_permission_error_for_nonexistent(self, mock_db):
        with pytest.raises(PermissionError):
            await get_notification_log(mock_db, rider_id=1, contact_id="no-such-uuid")


# ---------------------------------------------------------------------------
# Service: send_trusted_contact_notifications
# ---------------------------------------------------------------------------


class TestSendTrustedContactNotifications:
    @pytest.mark.asyncio
    async def test_trip_start_notifies_correct_contacts(self, mock_db):
        await _make_contact(mock_db, rider_id=1, phone="+15550000001", notify_on_trip_start=True)
        await _make_contact(mock_db, rider_id=1, phone="+15550000002", notify_on_trip_start=False)
        result = await send_trusted_contact_notifications(
            mock_db, ride_id=10, rider_id=1,
            notification_type=TrustedContactNotificationType.TRIP_START,
        )
        assert len(result) == 1
        assert result[0]["notification_type"] == TrustedContactNotificationType.TRIP_START

    @pytest.mark.asyncio
    async def test_panic_notifies_correct_contacts(self, mock_db):
        await _make_contact(mock_db, rider_id=1, phone="+15550000001", notify_on_panic=True)
        await _make_contact(mock_db, rider_id=1, phone="+15550000002", notify_on_panic=False)
        result = await send_trusted_contact_notifications(
            mock_db, ride_id=10, rider_id=1,
            notification_type=TrustedContactNotificationType.PANIC_ALERT,
        )
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_skips_inactive_contacts(self, mock_db):
        c = await _make_contact(mock_db, rider_id=1, phone="+15550000001")
        await deactivate_trusted_contact(mock_db, rider_id=1, contact_id=c["id"])
        result = await send_trusted_contact_notifications(
            mock_db, ride_id=10, rider_id=1,
            notification_type=TrustedContactNotificationType.TRIP_START,
        )
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_delivery_status_is_sent(self, mock_db):
        await _make_contact(mock_db, rider_id=1)
        result = await send_trusted_contact_notifications(
            mock_db, ride_id=10, rider_id=1,
            notification_type=TrustedContactNotificationType.TRIP_END,
        )
        assert result[0]["delivery_status"] == TrustedContactDeliveryStatus.SENT

    @pytest.mark.asyncio
    async def test_message_preview_is_populated(self, mock_db):
        await _make_contact(mock_db, rider_id=1)
        result = await send_trusted_contact_notifications(
            mock_db, ride_id=10, rider_id=1,
            notification_type=TrustedContactNotificationType.PANIC_ALERT,
        )
        assert len(result[0]["message_preview"]) > 0
        assert "panic" in result[0]["message_preview"].lower() or "URGENT" in result[0]["message_preview"]

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_contacts(self, mock_db):
        result = await send_trusted_contact_notifications(
            mock_db, ride_id=10, rider_id=99,
            notification_type=TrustedContactNotificationType.TRIP_START,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_notifies_multiple_contacts(self, mock_db):
        await _make_contact(mock_db, rider_id=1, phone="+15550000001")
        await _make_contact(mock_db, rider_id=1, phone="+15550000002")
        await _make_contact(mock_db, rider_id=1, phone="+15550000003")
        result = await send_trusted_contact_notifications(
            mock_db, ride_id=10, rider_id=1,
            notification_type=TrustedContactNotificationType.TRIP_START,
        )
        assert len(result) == 3


# ---------------------------------------------------------------------------
# Router tests
# ---------------------------------------------------------------------------


class TestTriggerPanicRouter:
    @pytest.mark.asyncio
    async def test_delegates_to_service(self):
        from unittest.mock import AsyncMock as AM, MagicMock as MM

        mock_rider = MM()
        mock_rider.id = 1

        mock_ride = MM()
        mock_ride.id = 100
        mock_ride.driver_id = 2
        mock_ride.status.value = "in_progress"

        expected = {
            "id": "abc-uuid",
            "ride_id": 100,
            "rider_id": 1,
            "driver_id": 2,
            "triggered_at": _utc_now(),
            "location_lat": None,
            "location_lng": None,
            "status": PanicAlertStatus.ACTIVE,
            "resolved_at": None,
            "resolved_by": None,
            "resolution_notes": None,
        }

        mock_db_session = AM()

        # Mock the DB query for the active ride
        mock_result = MM()
        mock_result.scalar_one_or_none = MM(return_value=mock_ride)
        mock_db_session.execute = AM(return_value=mock_result)

        with patch(
            "app.api.v1.rider_safety.trigger_panic",
            new_callable=AM,
            return_value=expected,
        ):
            from app.api.v1.rider_safety import post_trigger_panic

            body = TriggerPanicRequest()
            result = await post_trigger_panic(body=body, rider=mock_rider, db=mock_db_session)

        assert result.ride_id == 100
        assert result.status == PanicAlertStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_400_when_service_raises_value_error(self):
        from fastapi import HTTPException
        from unittest.mock import AsyncMock as AM, MagicMock as MM

        mock_rider = MM()
        mock_rider.id = 1

        mock_ride = MM()
        mock_ride.id = 100
        mock_ride.driver_id = 2

        mock_db_session = AM()
        mock_result = MM()
        mock_result.scalar_one_or_none = MM(return_value=mock_ride)
        mock_db_session.execute = AM(return_value=mock_result)

        with patch(
            "app.api.v1.rider_safety.trigger_panic",
            new_callable=AM,
            side_effect=ValueError("Duplicate active alert"),
        ):
            from app.api.v1.rider_safety import post_trigger_panic

            body = TriggerPanicRequest()
            with pytest.raises(HTTPException) as exc_info:
                await post_trigger_panic(body=body, rider=mock_rider, db=mock_db_session)

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_400_when_no_active_ride(self):
        from fastapi import HTTPException
        from unittest.mock import AsyncMock as AM, MagicMock as MM

        mock_rider = MM()
        mock_rider.id = 1

        mock_db_session = AM()
        mock_result = MM()
        mock_result.scalar_one_or_none = MM(return_value=None)
        mock_db_session.execute = AM(return_value=mock_result)

        from app.api.v1.rider_safety import post_trigger_panic

        body = TriggerPanicRequest()
        with pytest.raises(HTTPException) as exc_info:
            await post_trigger_panic(body=body, rider=mock_rider, db=mock_db_session)

        assert exc_info.value.status_code == 400


class TestGetPanicAlertRouter:
    @pytest.mark.asyncio
    async def test_404_when_service_returns_none(self):
        from fastapi import HTTPException

        mock_rider = MagicMock()
        mock_rider.id = 1

        with patch(
            "app.api.v1.rider_safety.get_panic_alert",
            new_callable=AsyncMock,
            return_value=None,
        ):
            from app.api.v1.rider_safety import get_panic_alert_endpoint

            with pytest.raises(HTTPException) as exc_info:
                await get_panic_alert_endpoint(
                    alert_id="no-uuid", rider=mock_rider, db=AsyncMock()
                )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_response_when_found(self):
        mock_rider = MagicMock()
        mock_rider.id = 1

        alert_data = {
            "id": "test-uuid",
            "ride_id": 10,
            "rider_id": 1,
            "driver_id": 2,
            "triggered_at": _utc_now(),
            "location_lat": None,
            "location_lng": None,
            "status": PanicAlertStatus.ACTIVE,
            "resolved_at": None,
            "resolved_by": None,
            "resolution_notes": None,
        }

        with patch(
            "app.api.v1.rider_safety.get_panic_alert",
            new_callable=AsyncMock,
            return_value=alert_data,
        ):
            from app.api.v1.rider_safety import get_panic_alert_endpoint

            result = await get_panic_alert_endpoint(
                alert_id="test-uuid", rider=mock_rider, db=AsyncMock()
            )

        assert result.id == "test-uuid"


class TestCancelPanicAlertRouter:
    @pytest.mark.asyncio
    async def test_404_when_permission_error(self):
        from fastapi import HTTPException

        mock_rider = MagicMock()
        mock_rider.id = 1

        with patch(
            "app.api.v1.rider_safety.cancel_panic_alert",
            new_callable=AsyncMock,
            side_effect=PermissionError("Not owner"),
        ):
            from app.api.v1.rider_safety import delete_cancel_panic_alert

            with pytest.raises(HTTPException) as exc_info:
                await delete_cancel_panic_alert(
                    alert_id="some-uuid", rider=mock_rider, db=AsyncMock()
                )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_400_when_value_error(self):
        from fastapi import HTTPException

        mock_rider = MagicMock()
        mock_rider.id = 1

        with patch(
            "app.api.v1.rider_safety.cancel_panic_alert",
            new_callable=AsyncMock,
            side_effect=ValueError("Already resolved"),
        ):
            from app.api.v1.rider_safety import delete_cancel_panic_alert

            with pytest.raises(HTTPException) as exc_info:
                await delete_cancel_panic_alert(
                    alert_id="some-uuid", rider=mock_rider, db=AsyncMock()
                )

        assert exc_info.value.status_code == 400


class TestAdminListPanicAlertsRouter:
    @pytest.mark.asyncio
    async def test_returns_panic_alert_list_response(self):
        mock_admin = MagicMock()
        mock_admin.id = 99

        with patch(
            "app.api.v1.rider_safety.admin_list_active_panic_alerts",
            new_callable=AsyncMock,
            return_value=(0, []),
        ):
            from app.api.v1.rider_safety import admin_get_active_panic_alerts

            result = await admin_get_active_panic_alerts(
                skip=0, limit=50, admin=mock_admin, db=AsyncMock()
            )

        assert isinstance(result, PanicAlertListResponse)
        assert result.total == 0
        assert result.items == []


class TestAdminResolvePanicAlertRouter:
    @pytest.mark.asyncio
    async def test_404_on_key_error(self):
        from fastapi import HTTPException

        mock_admin = MagicMock()
        mock_admin.id = 99

        with patch(
            "app.api.v1.rider_safety.admin_resolve_panic_alert",
            new_callable=AsyncMock,
            side_effect=KeyError("not found"),
        ):
            from app.api.v1.rider_safety import admin_post_resolve_panic_alert

            body = AdminResolvePanicRequest()
            with pytest.raises(HTTPException) as exc_info:
                await admin_post_resolve_panic_alert(
                    alert_id="no-uuid", body=body, admin=mock_admin, db=AsyncMock()
                )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_400_on_value_error(self):
        from fastapi import HTTPException

        mock_admin = MagicMock()
        mock_admin.id = 99

        with patch(
            "app.api.v1.rider_safety.admin_resolve_panic_alert",
            new_callable=AsyncMock,
            side_effect=ValueError("Already resolved"),
        ):
            from app.api.v1.rider_safety import admin_post_resolve_panic_alert

            body = AdminResolvePanicRequest()
            with pytest.raises(HTTPException) as exc_info:
                await admin_post_resolve_panic_alert(
                    alert_id="some-uuid", body=body, admin=mock_admin, db=AsyncMock()
                )

        assert exc_info.value.status_code == 400


class TestAddTrustedContactRouter:
    @pytest.mark.asyncio
    async def test_400_when_max_contacts_exceeded(self):
        from fastapi import HTTPException

        mock_rider = MagicMock()
        mock_rider.id = 1

        with patch(
            "app.api.v1.rider_safety.add_trusted_contact",
            new_callable=AsyncMock,
            side_effect=ValueError("at most 3 active trusted contacts"),
        ):
            from app.api.v1.rider_safety import post_add_trusted_contact

            body = TrustedContactCreate(name="Extra", phone="+15550000099")
            with pytest.raises(HTTPException) as exc_info:
                await post_add_trusted_contact(body=body, rider=mock_rider, db=AsyncMock())

        assert exc_info.value.status_code == 400


class TestUpdateTrustedContactRouter:
    @pytest.mark.asyncio
    async def test_404_on_permission_error(self):
        from fastapi import HTTPException

        mock_rider = MagicMock()
        mock_rider.id = 1

        with patch(
            "app.api.v1.rider_safety.update_trusted_contact",
            new_callable=AsyncMock,
            side_effect=PermissionError("Not owner"),
        ):
            from app.api.v1.rider_safety import put_update_trusted_contact

            body = TrustedContactUpdate(name="Hacker")
            with pytest.raises(HTTPException) as exc_info:
                await put_update_trusted_contact(
                    contact_id="no-uuid", body=body, rider=mock_rider, db=AsyncMock()
                )

        assert exc_info.value.status_code == 404


class TestDeactivateTrustedContactRouter:
    @pytest.mark.asyncio
    async def test_404_on_permission_error(self):
        from fastapi import HTTPException

        mock_rider = MagicMock()
        mock_rider.id = 1

        with patch(
            "app.api.v1.rider_safety.deactivate_trusted_contact",
            new_callable=AsyncMock,
            side_effect=PermissionError("Not owner"),
        ):
            from app.api.v1.rider_safety import delete_deactivate_trusted_contact

            with pytest.raises(HTTPException) as exc_info:
                await delete_deactivate_trusted_contact(
                    contact_id="no-uuid", rider=mock_rider, db=AsyncMock()
                )

        assert exc_info.value.status_code == 404


class TestGetNotificationLogRouter:
    @pytest.mark.asyncio
    async def test_404_on_permission_error(self):
        from fastapi import HTTPException

        mock_rider = MagicMock()
        mock_rider.id = 1

        with patch(
            "app.api.v1.rider_safety.get_notification_log",
            new_callable=AsyncMock,
            side_effect=PermissionError("Not owner"),
        ):
            from app.api.v1.rider_safety import get_contact_notification_log

            with pytest.raises(HTTPException) as exc_info:
                await get_contact_notification_log(
                    contact_id="no-uuid", rider=mock_rider, db=AsyncMock()
                )

        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# End-to-end: panic alert flow
# ---------------------------------------------------------------------------


class TestPanicAlertEndToEnd:
    @pytest.mark.asyncio
    async def test_trigger_appears_in_admin_list_then_admin_resolves(self, mock_db):
        # Trigger
        alert = await trigger_panic(mock_db, rider_id=1, ride_id=100, driver_id=2)
        assert alert["status"] == PanicAlertStatus.ACTIVE

        # Admin sees it
        total, items = await admin_list_active_panic_alerts(mock_db)
        assert total == 1
        assert items[0]["id"] == alert["id"]

        # Admin resolves it
        resolved = await admin_resolve_panic_alert(
            mock_db, alert["id"], admin_id=99, resolution_notes="Checked on rider, all OK."
        )
        assert resolved["status"] == PanicAlertStatus.RESOLVED
        assert resolved["resolved_by"] == 99

        # No longer in active list
        total2, items2 = await admin_list_active_panic_alerts(mock_db)
        assert total2 == 0

    @pytest.mark.asyncio
    async def test_panic_triggers_trusted_contact_notifications(self, mock_db):
        await add_trusted_contact(
            mock_db, rider_id=1, name="Alice", phone="+15551111111",
            notify_on_panic=True, notify_on_trip_start=True, notify_on_trip_end=True,
        )
        await add_trusted_contact(
            mock_db, rider_id=1, name="Bob", phone="+15552222222",
            notify_on_panic=False, notify_on_trip_start=True, notify_on_trip_end=True,
        )

        # Trigger panic
        await trigger_panic(mock_db, rider_id=1, ride_id=100, driver_id=2)

        # Send panic notifications
        sent = await send_trusted_contact_notifications(
            mock_db, ride_id=100, rider_id=1,
            notification_type=TrustedContactNotificationType.PANIC_ALERT,
        )
        # Only Alice has notify_on_panic=True
        assert len(sent) == 1
        assert "URGENT" in sent[0]["message_preview"] or "panic" in sent[0]["message_preview"].lower()


# ---------------------------------------------------------------------------
# End-to-end: trusted contact limit
# ---------------------------------------------------------------------------


class TestTrustedContactLimitEndToEnd:
    @pytest.mark.asyncio
    async def test_exactly_3_contacts_allowed(self, mock_db):
        for i in range(3):
            c = await add_trusted_contact(
                mock_db, rider_id=1, name=f"Contact {i}", phone=f"+1555000000{i}"
            )
            assert c["is_active"] is True

    @pytest.mark.asyncio
    async def test_4th_contact_raises_value_error(self, mock_db):
        for i in range(3):
            await add_trusted_contact(
                mock_db, rider_id=1, name=f"Contact {i}", phone=f"+1555000000{i}"
            )
        with pytest.raises(ValueError):
            await add_trusted_contact(
                mock_db, rider_id=1, name="Too Many", phone="+15550000099"
            )

    @pytest.mark.asyncio
    async def test_deactivate_and_re_add(self, mock_db):
        contacts = []
        for i in range(3):
            c = await add_trusted_contact(
                mock_db, rider_id=1, name=f"Contact {i}", phone=f"+1555000000{i}"
            )
            contacts.append(c)

        # Deactivate first
        await deactivate_trusted_contact(mock_db, rider_id=1, contact_id=contacts[0]["id"])

        # Now can add again
        new_c = await add_trusted_contact(
            mock_db, rider_id=1, name="New Contact", phone="+15550000099"
        )
        assert new_c["is_active"] is True
