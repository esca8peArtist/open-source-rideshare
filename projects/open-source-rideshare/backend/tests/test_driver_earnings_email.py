"""Tests for post-ride driver earnings email.

Covers:
- NotificationType entry exists for driver_earnings
- Template returns EMAIL-only channel
- Template title includes ride ID
- Template body includes route (pickup → dropoff)
- Template body includes earnings breakdown fields (base, distance, time)
- Template body includes surge/bonus when non-zero
- Template body includes tip when non-zero
- Template body includes platform commission
- Template body includes net payout
- Template body includes rider name and rating given
- Template body includes today's totals when provided
- Template body omits zero surge/tip
- render() dispatch works via NotificationType.DRIVER_EARNINGS
- notify_driver_earnings sends exactly one email
- notify_driver_earnings sends to driver's email address
- notify_driver_earnings notification type is DRIVER_EARNINGS
- notify_driver_earnings ride_id attributed correctly
- notify_driver_earnings sends only EMAIL channel
- notify_driver_earnings does nothing when driver has no email
- notify_driver_earnings does nothing when earnings data unavailable (None receipt)
- notify_driver_earnings failure does not raise
- Wiring: complete_ride calls notify_driver_earnings
- Wiring: driver earnings email failure does not block ride completion
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
from app.services.notification_templates import driver_earnings, render


# ---------------------------------------------------------------------------
# Enum presence
# ---------------------------------------------------------------------------


class TestNotificationTypeEntry:
    def test_driver_earnings_exists(self):
        assert NotificationType.DRIVER_EARNINGS == "driver_earnings"


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------


_FULL_KWARGS = dict(
    ride_id=42,
    trip_date="2026-04-23",
    pickup_address="123 Main St",
    dropoff_address="456 Oak Ave",
    fare_base=2.50,
    fare_distance_comp=3.20,
    fare_time_comp=1.80,
    surge_bonus=1.00,
    tip=2.00,
    platform_commission=1.50,
    net_payout=9.00,
    rider_name="Jane Rider",
    rider_rating_given=5.0,
    total_rides_today=5,
    total_earnings_today=65.00,
)


class TestDriverEarningsTemplate:
    def test_channel_email_only(self):
        _, _, channels = driver_earnings(**_FULL_KWARGS)
        assert channels == [NotificationChannel.EMAIL]
        assert NotificationChannel.PUSH not in channels
        assert NotificationChannel.SMS not in channels

    def test_title_includes_ride_id(self):
        title, _, _ = driver_earnings(**_FULL_KWARGS)
        assert "42" in title

    def test_title_without_ride_id(self):
        title, _, _ = driver_earnings()
        assert "earnings" in title.lower() or "trip" in title.lower()

    def test_body_includes_route(self):
        _, body, _ = driver_earnings(**_FULL_KWARGS)
        assert "123 Main St" in body
        assert "456 Oak Ave" in body

    def test_body_includes_fare_base(self):
        _, body, _ = driver_earnings(**_FULL_KWARGS)
        assert "2.5" in body or "2.50" in body

    def test_body_includes_fare_distance(self):
        _, body, _ = driver_earnings(**_FULL_KWARGS)
        assert "3.2" in body or "3.20" in body

    def test_body_includes_fare_time(self):
        _, body, _ = driver_earnings(**_FULL_KWARGS)
        assert "1.8" in body or "1.80" in body

    def test_body_includes_surge_bonus(self):
        _, body, _ = driver_earnings(**_FULL_KWARGS)
        assert "1.0" in body or "1.00" in body

    def test_body_includes_tip(self):
        _, body, _ = driver_earnings(**_FULL_KWARGS)
        assert "2.0" in body or "2.00" in body

    def test_body_includes_platform_commission(self):
        _, body, _ = driver_earnings(**_FULL_KWARGS)
        assert "1.5" in body or "1.50" in body

    def test_body_includes_net_payout(self):
        _, body, _ = driver_earnings(**_FULL_KWARGS)
        assert "9.0" in body or "9.00" in body

    def test_body_includes_rider_name(self):
        _, body, _ = driver_earnings(**_FULL_KWARGS)
        assert "Jane Rider" in body

    def test_body_includes_rider_rating(self):
        _, body, _ = driver_earnings(**_FULL_KWARGS)
        assert "5.0" in body

    def test_body_includes_total_rides_today(self):
        _, body, _ = driver_earnings(**_FULL_KWARGS)
        assert "5" in body

    def test_body_includes_total_earnings_today(self):
        _, body, _ = driver_earnings(**_FULL_KWARGS)
        assert "65.0" in body or "65.00" in body

    def test_body_omits_zero_surge(self):
        kwargs = {**_FULL_KWARGS, "surge_bonus": 0}
        _, body, _ = driver_earnings(**kwargs)
        assert "Surge" not in body

    def test_body_omits_zero_tip(self):
        kwargs = {**_FULL_KWARGS, "tip": 0}
        _, body, _ = driver_earnings(**kwargs)
        assert "Tip" not in body

    def test_render_dispatch(self):
        title, body, channels = render(NotificationType.DRIVER_EARNINGS, **_FULL_KWARGS)
        assert NotificationChannel.EMAIL in channels
        assert "Jane Rider" in body
        assert "42" in title


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
            "platform_fee": 1.50,
            "total": 9.00,
        },
        "promo_discount": 0.0,
        "tip": 1.00,
        "total_charged": 10.00,
        "payment": {
            "platform_fee": 1.50,
            "driver_payout": 8.50,
        },
        "rider": {
            "name": "Jane Rider",
        },
        "rider_rating_given": 5.0,
        "requested_at": None,
        "started_at": None,
        "completed_at": None,
    }


@pytest.mark.asyncio
class TestNotifyDriverEarningsDispatcher:
    async def test_sends_one_email(self):
        clear_sent_notifications()
        db = _make_db()

        with (
            patch(
                "app.services.notification_events._get_user_contact",
                new=AsyncMock(return_value=(None, "driver@example.com")),
            ),
            patch(
                "app.services.receipts.generate_receipt",
                new=AsyncMock(return_value=_make_receipt(42)),
            ),
        ):
            from app.services.notification_events import notify_driver_earnings
            await notify_driver_earnings(db, driver_id=20, ride_id=42)

        sent = [n for n in get_sent_notifications() if n.type == NotificationType.DRIVER_EARNINGS]
        assert len(sent) == 1

    async def test_notification_type_is_driver_earnings(self):
        clear_sent_notifications()
        db = _make_db()

        with (
            patch(
                "app.services.notification_events._get_user_contact",
                new=AsyncMock(return_value=(None, "driver@example.com")),
            ),
            patch(
                "app.services.receipts.generate_receipt",
                new=AsyncMock(return_value=_make_receipt(42)),
            ),
        ):
            from app.services.notification_events import notify_driver_earnings
            await notify_driver_earnings(db, driver_id=20, ride_id=42)

        sent = get_sent_notifications()
        assert sent[-1].type == NotificationType.DRIVER_EARNINGS

    async def test_ride_id_attributed(self):
        clear_sent_notifications()
        db = _make_db()

        with (
            patch(
                "app.services.notification_events._get_user_contact",
                new=AsyncMock(return_value=(None, "driver@example.com")),
            ),
            patch(
                "app.services.receipts.generate_receipt",
                new=AsyncMock(return_value=_make_receipt(99)),
            ),
        ):
            from app.services.notification_events import notify_driver_earnings
            await notify_driver_earnings(db, driver_id=20, ride_id=99)

        sent = [n for n in get_sent_notifications() if n.type == NotificationType.DRIVER_EARNINGS]
        assert sent[0].ride_id == 99

    async def test_email_channel_only(self):
        clear_sent_notifications()
        db = _make_db()

        with (
            patch(
                "app.services.notification_events._get_user_contact",
                new=AsyncMock(return_value=(None, "driver@example.com")),
            ),
            patch(
                "app.services.receipts.generate_receipt",
                new=AsyncMock(return_value=_make_receipt(42)),
            ),
        ):
            from app.services.notification_events import notify_driver_earnings
            await notify_driver_earnings(db, driver_id=20, ride_id=42)

        sent = [n for n in get_sent_notifications() if n.type == NotificationType.DRIVER_EARNINGS]
        assert sent[0].channels == [NotificationChannel.EMAIL]

    async def test_does_nothing_when_no_email(self):
        clear_sent_notifications()
        db = _make_db()

        with patch(
            "app.services.notification_events._get_user_contact",
            new=AsyncMock(return_value=(None, None)),
        ):
            from app.services.notification_events import notify_driver_earnings
            await notify_driver_earnings(db, driver_id=20, ride_id=42)

        sent = [n for n in get_sent_notifications() if n.type == NotificationType.DRIVER_EARNINGS]
        assert len(sent) == 0

    async def test_does_nothing_when_receipt_returns_none(self):
        clear_sent_notifications()
        db = _make_db()

        with (
            patch(
                "app.services.notification_events._get_user_contact",
                new=AsyncMock(return_value=(None, "driver@example.com")),
            ),
            patch(
                "app.services.receipts.generate_receipt",
                new=AsyncMock(return_value=None),
            ),
        ):
            from app.services.notification_events import notify_driver_earnings
            await notify_driver_earnings(db, driver_id=20, ride_id=42)

        sent = [n for n in get_sent_notifications() if n.type == NotificationType.DRIVER_EARNINGS]
        assert len(sent) == 0

    async def test_failure_does_not_raise(self):
        db = _make_db()

        with patch(
            "app.services.notification_events._get_user_contact",
            new=AsyncMock(side_effect=RuntimeError("db exploded")),
        ):
            from app.services.notification_events import notify_driver_earnings
            await notify_driver_earnings(db, driver_id=20, ride_id=42)  # must not raise


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
@patch("app.services.notification_events.notify_trip_receipt", new_callable=AsyncMock)
async def test_complete_ride_calls_notify_driver_earnings(
    mock_receipt, mock_referral, mock_incentive, mock_fatigue, mock_trusted,
    mock_audit, mock_completed_driver, mock_completed, mock_engine_fn, mock_ws,
):
    """notify_driver_earnings is called when a ride is completed."""
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
    earnings_called = []

    async def fake_earnings(db2, driver_id, ride_id):
        earnings_called.append(ride_id)

    with patch("app.services.notification_events.notify_driver_earnings", new=fake_earnings):
        await complete_ride(ride_id=7, driver=driver, db=db)

    assert 7 in earnings_called


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
@patch("app.services.notification_events.notify_trip_receipt", new_callable=AsyncMock)
async def test_driver_earnings_email_failure_does_not_block_completion(
    mock_receipt, mock_referral, mock_incentive, mock_fatigue, mock_trusted,
    mock_audit, mock_completed_driver, mock_completed, mock_engine_fn, mock_ws,
):
    """A crash in notify_driver_earnings must not prevent ride completion."""
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

    async def crashing_earnings(db2, driver_id, ride_id):
        raise RuntimeError("email provider down")

    with patch("app.services.notification_events.notify_driver_earnings", new=crashing_earnings):
        result = await complete_ride(ride_id=8, driver=driver, db=db)

    assert result["status"] == "completed"
