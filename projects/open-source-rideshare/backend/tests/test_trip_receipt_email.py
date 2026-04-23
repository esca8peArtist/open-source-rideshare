"""Tests for post-ride trip receipt email.

Covers:
- NotificationType entry exists for trip_receipt
- Template returns EMAIL-only channel
- Template title includes receipt number
- Template body includes route (pickup → dropoff)
- Template body includes fare breakdown fields (base, distance, time)
- Template body includes promo discount when non-zero
- Template body includes tip when non-zero
- Template body includes total charged
- Template body includes driver name and rating
- Template body includes driver vehicle
- Template body omits zero promo/tip
- render() dispatch works via NotificationType.TRIP_RECEIPT
- notify_trip_receipt sends exactly one email
- notify_trip_receipt sends to user's email address
- notify_trip_receipt notification type is TRIP_RECEIPT
- notify_trip_receipt ride_id attributed correctly
- notify_trip_receipt does nothing when receipt returns None
- notify_trip_receipt does nothing when user has no email
- notify_trip_receipt failure does not raise
- Wiring: complete_ride calls notify_trip_receipt
- Wiring: receipt email failure does not block ride completion
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.notifications import (
    NotificationChannel,
    NotificationType,
    clear_sent_notifications,
    get_sent_notifications,
)
from app.services.notification_templates import trip_receipt, render


# ---------------------------------------------------------------------------
# Enum presence
# ---------------------------------------------------------------------------


class TestNotificationTypeEntry:
    def test_trip_receipt_exists(self):
        assert NotificationType.TRIP_RECEIPT == "trip_receipt"


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------


_FULL_KWARGS = dict(
    receipt_number="OR-00000042",
    pickup_address="123 Main St",
    dropoff_address="456 Oak Ave",
    distance_km=8.5,
    duration_min=22.0,
    fare_base=2.50,
    fare_distance_comp=3.20,
    fare_time_comp=1.80,
    promo_discount=1.00,
    tip=2.00,
    total_charged=8.50,
    driver_name="Alice Smith",
    driver_rating=4.8,
    driver_vehicle="White Toyota Camry",
)


class TestTripReceiptTemplate:
    def test_channel_email_only(self):
        _, _, channels = trip_receipt(**_FULL_KWARGS)
        assert channels == [NotificationChannel.EMAIL]
        assert NotificationChannel.PUSH not in channels
        assert NotificationChannel.SMS not in channels

    def test_title_includes_receipt_number(self):
        title, _, _ = trip_receipt(**_FULL_KWARGS)
        assert "OR-00000042" in title

    def test_title_without_receipt_number(self):
        title, _, _ = trip_receipt()
        assert "receipt" in title.lower() or "trip" in title.lower()

    def test_body_includes_route(self):
        _, body, _ = trip_receipt(**_FULL_KWARGS)
        assert "123 Main St" in body
        assert "456 Oak Ave" in body

    def test_body_includes_fare_base(self):
        _, body, _ = trip_receipt(**_FULL_KWARGS)
        assert "2.5" in body or "2.50" in body

    def test_body_includes_fare_distance(self):
        _, body, _ = trip_receipt(**_FULL_KWARGS)
        assert "3.2" in body or "3.20" in body

    def test_body_includes_fare_time(self):
        _, body, _ = trip_receipt(**_FULL_KWARGS)
        assert "1.8" in body or "1.80" in body

    def test_body_includes_promo_discount(self):
        _, body, _ = trip_receipt(**_FULL_KWARGS)
        assert "1.0" in body or "1.00" in body

    def test_body_includes_tip(self):
        _, body, _ = trip_receipt(**_FULL_KWARGS)
        assert "2.0" in body or "2.00" in body

    def test_body_includes_total(self):
        _, body, _ = trip_receipt(**_FULL_KWARGS)
        assert "8.5" in body or "8.50" in body

    def test_body_includes_driver_name(self):
        _, body, _ = trip_receipt(**_FULL_KWARGS)
        assert "Alice Smith" in body

    def test_body_includes_driver_rating(self):
        _, body, _ = trip_receipt(**_FULL_KWARGS)
        assert "4.8" in body

    def test_body_includes_driver_vehicle(self):
        _, body, _ = trip_receipt(**_FULL_KWARGS)
        assert "White Toyota Camry" in body

    def test_body_omits_zero_promo(self):
        kwargs = {**_FULL_KWARGS, "promo_discount": 0}
        _, body, _ = trip_receipt(**kwargs)
        assert "Promo" not in body

    def test_body_omits_zero_tip(self):
        kwargs = {**_FULL_KWARGS, "tip": 0}
        _, body, _ = trip_receipt(**kwargs)
        assert "Tip" not in body

    def test_render_dispatch(self):
        title, body, channels = render(NotificationType.TRIP_RECEIPT, **_FULL_KWARGS)
        assert NotificationChannel.EMAIL in channels
        assert "Alice Smith" in body
        assert "OR-00000042" in title


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


def _make_db():
    return AsyncMock()


def _make_receipt(ride_id=42):
    return {
        "ride_id": ride_id,
        "receipt_number": f"OR-{ride_id:08d}",
        "pickup_address": "123 Main St",
        "dropoff_address": "456 Oak Ave",
        "distance_km": 8.5,
        "duration_min": 22.0,
        "fare_breakdown": {
            "base": 2.50,
            "distance": 3.20,
            "time": 1.80,
            "multiplier": 1.0,
            "multiplier_label": "",
            "subtotal": 7.50,
            "platform_fee": 0.50,
            "total": 8.00,
        },
        "promo_discount": 0.50,
        "tip": 1.00,
        "total_charged": 8.50,
        "driver": {
            "name": "Bob Driver",
            "rating": 4.7,
            "vehicle": "Blue Honda Accord",
            "license_plate": "XYZ-789",
        },
        "requested_at": None,
        "started_at": None,
        "completed_at": None,
    }


@pytest.mark.asyncio
class TestNotifyTripReceiptDispatcher:
    async def test_sends_one_email(self):
        clear_sent_notifications()
        db = _make_db()

        with (
            patch(
                "app.services.notification_events._get_user_contact",
                new=AsyncMock(return_value=(None, "rider@example.com")),
            ),
            patch(
                "app.services.receipts.generate_receipt",
                new=AsyncMock(return_value=_make_receipt(42)),
            ),
        ):
            from app.services.notification_events import notify_trip_receipt
            await notify_trip_receipt(db, rider_id=1, ride_id=42)

        sent = [n for n in get_sent_notifications() if n.type == NotificationType.TRIP_RECEIPT]
        assert len(sent) == 1

    async def test_notification_type_is_trip_receipt(self):
        clear_sent_notifications()
        db = _make_db()

        with (
            patch(
                "app.services.notification_events._get_user_contact",
                new=AsyncMock(return_value=(None, "rider@example.com")),
            ),
            patch(
                "app.services.receipts.generate_receipt",
                new=AsyncMock(return_value=_make_receipt(42)),
            ),
        ):
            from app.services.notification_events import notify_trip_receipt
            await notify_trip_receipt(db, rider_id=1, ride_id=42)

        sent = get_sent_notifications()
        assert sent[-1].type == NotificationType.TRIP_RECEIPT

    async def test_ride_id_attributed(self):
        clear_sent_notifications()
        db = _make_db()

        with (
            patch(
                "app.services.notification_events._get_user_contact",
                new=AsyncMock(return_value=(None, "rider@example.com")),
            ),
            patch(
                "app.services.receipts.generate_receipt",
                new=AsyncMock(return_value=_make_receipt(99)),
            ),
        ):
            from app.services.notification_events import notify_trip_receipt
            await notify_trip_receipt(db, rider_id=1, ride_id=99)

        sent = [n for n in get_sent_notifications() if n.type == NotificationType.TRIP_RECEIPT]
        assert sent[0].ride_id == 99

    async def test_email_channel_only(self):
        clear_sent_notifications()
        db = _make_db()

        with (
            patch(
                "app.services.notification_events._get_user_contact",
                new=AsyncMock(return_value=(None, "rider@example.com")),
            ),
            patch(
                "app.services.receipts.generate_receipt",
                new=AsyncMock(return_value=_make_receipt(42)),
            ),
        ):
            from app.services.notification_events import notify_trip_receipt
            await notify_trip_receipt(db, rider_id=1, ride_id=42)

        sent = [n for n in get_sent_notifications() if n.type == NotificationType.TRIP_RECEIPT]
        assert sent[0].channels == [NotificationChannel.EMAIL]

    async def test_does_nothing_when_no_email(self):
        clear_sent_notifications()
        db = _make_db()

        with patch(
            "app.services.notification_events._get_user_contact",
            new=AsyncMock(return_value=(None, None)),
        ):
            from app.services.notification_events import notify_trip_receipt
            await notify_trip_receipt(db, rider_id=1, ride_id=42)

        sent = [n for n in get_sent_notifications() if n.type == NotificationType.TRIP_RECEIPT]
        assert len(sent) == 0

    async def test_does_nothing_when_receipt_returns_none(self):
        clear_sent_notifications()
        db = _make_db()

        with (
            patch(
                "app.services.notification_events._get_user_contact",
                new=AsyncMock(return_value=(None, "rider@example.com")),
            ),
            patch(
                "app.services.receipts.generate_receipt",
                new=AsyncMock(return_value=None),
            ),
        ):
            from app.services.notification_events import notify_trip_receipt
            await notify_trip_receipt(db, rider_id=1, ride_id=42)

        sent = [n for n in get_sent_notifications() if n.type == NotificationType.TRIP_RECEIPT]
        assert len(sent) == 0

    async def test_failure_does_not_raise(self):
        db = _make_db()

        with patch(
            "app.services.notification_events._get_user_contact",
            new=AsyncMock(side_effect=RuntimeError("db exploded")),
        ):
            from app.services.notification_events import notify_trip_receipt
            await notify_trip_receipt(db, rider_id=1, ride_id=42)  # must not raise


# ---------------------------------------------------------------------------
# Wiring — complete_ride
# ---------------------------------------------------------------------------


def _make_complete_ride_db(ride, estimated_fare=9.00):
    """Build a mock DB that serves the 4 execute calls made by complete_ride."""
    ride_result = MagicMock()
    ride_result.scalar_one_or_none.return_value = ride

    count_result = MagicMock()
    count_result.scalar.return_value = 1  # not first ride

    rider_obj = MagicMock()
    rider_obj.referred_by = None
    rider_result = MagicMock()
    rider_result.scalar_one_or_none.return_value = rider_obj

    profile = MagicMock()
    profile.total_trips = 5
    profile_result = MagicMock()
    profile_result.scalar_one_or_none.return_value = profile

    db = AsyncMock()
    db.execute.side_effect = [ride_result, count_result, rider_result, profile_result]
    return db


@pytest.mark.asyncio
@patch("app.api.websocket.notify_ride_status", new_callable=AsyncMock)
@patch("app.api.v1.rides.get_matching_engine", new_callable=AsyncMock)
@patch("app.services.notification_events.notify_ride_completed", new_callable=AsyncMock)
@patch("app.services.notification_events.notify_ride_completed_driver", new_callable=AsyncMock)
@patch("app.services.audit_events.audit_ride_completed", new_callable=AsyncMock)
@patch("app.services.rider_safety.send_trusted_contact_notifications", new_callable=AsyncMock)
@patch("app.services.driver_fatigue.log_ride_event")
@patch("app.services.incentives.record_trip_completion", new_callable=AsyncMock)
@patch("app.services.driver_referral.check_and_award_driver_referral_bonus", new_callable=AsyncMock)
async def test_complete_ride_calls_notify_trip_receipt(
    mock_referral, mock_incentive, mock_fatigue, mock_trusted,
    mock_audit, mock_completed_driver, mock_completed, mock_engine_fn, mock_ws,
):
    """notify_trip_receipt is called when a ride is completed."""
    from app.api.v1.rides import complete_ride
    from app.models.ride import Ride, RideStatus
    from app.models.user import User, UserRole

    mock_engine_fn.return_value = AsyncMock()

    driver = MagicMock(spec=User)
    driver.id = 20
    driver.name = "Driver Dave"
    driver.role = UserRole.DRIVER

    ride = MagicMock(spec=Ride)
    ride.id = 7
    ride.rider_id = 10
    ride.driver_id = 20
    ride.status = RideStatus.IN_PROGRESS
    ride.estimated_fare = 9.00
    ride.actual_fare = None
    ride.tip_amount = 0.0
    ride.promo_discount = 0.0
    ride.promo_code_id = None

    db = _make_complete_ride_db(ride)
    receipt_called = []

    async def fake_receipt(db2, rider_id, ride_id):
        receipt_called.append(ride_id)

    with patch("app.services.notification_events.notify_trip_receipt", new=fake_receipt):
        await complete_ride(ride_id=7, driver=driver, db=db)

    assert 7 in receipt_called


@pytest.mark.asyncio
@patch("app.api.websocket.notify_ride_status", new_callable=AsyncMock)
@patch("app.api.v1.rides.get_matching_engine", new_callable=AsyncMock)
@patch("app.services.notification_events.notify_ride_completed", new_callable=AsyncMock)
@patch("app.services.notification_events.notify_ride_completed_driver", new_callable=AsyncMock)
@patch("app.services.audit_events.audit_ride_completed", new_callable=AsyncMock)
@patch("app.services.rider_safety.send_trusted_contact_notifications", new_callable=AsyncMock)
@patch("app.services.driver_fatigue.log_ride_event")
@patch("app.services.incentives.record_trip_completion", new_callable=AsyncMock)
@patch("app.services.driver_referral.check_and_award_driver_referral_bonus", new_callable=AsyncMock)
async def test_receipt_email_failure_does_not_block_completion(
    mock_referral, mock_incentive, mock_fatigue, mock_trusted,
    mock_audit, mock_completed_driver, mock_completed, mock_engine_fn, mock_ws,
):
    """A crash in notify_trip_receipt must not prevent ride completion."""
    from app.api.v1.rides import complete_ride
    from app.models.ride import Ride, RideStatus
    from app.models.user import User, UserRole

    mock_engine_fn.return_value = AsyncMock()

    driver = MagicMock(spec=User)
    driver.id = 20
    driver.name = "Eve Driver"
    driver.role = UserRole.DRIVER

    ride = MagicMock(spec=Ride)
    ride.id = 8
    ride.rider_id = 15
    ride.driver_id = 20
    ride.status = RideStatus.IN_PROGRESS
    ride.estimated_fare = 5.00
    ride.actual_fare = None
    ride.tip_amount = 0.0
    ride.promo_discount = 0.0
    ride.promo_code_id = None

    db = _make_complete_ride_db(ride, estimated_fare=5.00)

    async def crashing_receipt(db2, rider_id, ride_id):
        raise RuntimeError("email provider down")

    with patch("app.services.notification_events.notify_trip_receipt", new=crashing_receipt):
        result = await complete_ride(ride_id=8, driver=driver, db=db)

    assert result["status"] == "completed"
