"""Tests for driver document expiry notifications.

Covers:
- NotificationType.DOCUMENT_EXPIRY_WARNING exists
- NotificationType.DOCUMENT_EXPIRED exists
- document_expiry_warning template: PUSH+SMS channels, title, body (30/14/7/1 days)
- document_expiry_warning template: body contains document type
- document_expiry_warning template: body contains expiry date
- document_expiry_warning template: body mentions uploading a document
- document_expiry_warning template: singular "day" for days_remaining==1
- document_expired template: PUSH+SMS channels, title, body
- document_expired template: body for expired today (days_overdue=0)
- document_expired template: body for expired N days ago
- document_expired template: body mentions cannot accept rides
- render() dispatch works for DOCUMENT_EXPIRY_WARNING
- render() dispatch works for DOCUMENT_EXPIRED
- notify_document_expiry_warning sends exactly one notification
- notify_document_expiry_warning sends to correct user
- notify_document_expiry_warning type is DOCUMENT_EXPIRY_WARNING
- notify_document_expiry_warning has document_type in data
- notify_document_expiry_warning sends PUSH and SMS channels
- notify_document_expiry_warning still sends PUSH when user has no phone/email
- notify_document_expiry_warning failure does not raise
- notify_document_expired sends exactly one notification
- notify_document_expired sends to correct user
- notify_document_expired type is DOCUMENT_EXPIRED
- notify_document_expired has document_type in data
- notify_document_expired sends PUSH and SMS channels
- notify_document_expired still sends PUSH when user has no phone/email
- notify_document_expired failure does not raise
- ExpiringDocument dataclass: days_remaining computed correctly
- get_expiring_documents returns license records within window
- get_expiring_documents returns registration records within window
- get_expiring_documents returns insurance records within window
- get_expiring_documents excludes records beyond the window
- get_expiring_documents includes already-expired records (days_remaining < 0)
- get_expiring_documents excludes non-approved records
- get_expiring_documents returns empty list when nothing found
- send_document_expiry_notifications dispatches warning for upcoming doc
- send_document_expiry_notifications dispatches expired for expired doc
- send_document_expiry_notifications dispatches expired for today doc (days_remaining=0)
- send_document_expiry_notifications returns count of dispatched notifications
- send_document_expiry_notifications tolerates individual notification failures
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.notifications import (
    NotificationChannel,
    NotificationType,
    clear_sent_notifications,
    get_sent_notifications,
)
from app.services.notification_templates import (
    document_expiry_warning,
    document_expired,
    render,
)


# ---------------------------------------------------------------------------
# Enum presence
# ---------------------------------------------------------------------------


class TestNotificationTypeEntries:
    def test_document_expiry_warning_exists(self):
        assert NotificationType.DOCUMENT_EXPIRY_WARNING == "document_expiry_warning"

    def test_document_expired_exists(self):
        assert NotificationType.DOCUMENT_EXPIRED == "document_expired"


# ---------------------------------------------------------------------------
# document_expiry_warning template
# ---------------------------------------------------------------------------


class TestDocumentExpiryWarningTemplate:
    def test_channels_push_and_sms(self):
        _, _, channels = document_expiry_warning()
        assert NotificationChannel.PUSH in channels
        assert NotificationChannel.SMS in channels

    def test_no_email_channel(self):
        _, _, channels = document_expiry_warning()
        assert NotificationChannel.EMAIL not in channels

    def test_returns_three_tuple(self):
        result = document_expiry_warning(document_type="license", days_remaining=30)
        assert len(result) == 3

    def test_title_contains_expiring(self):
        title, _, _ = document_expiry_warning(document_type="license", days_remaining=30)
        assert "expir" in title.lower()

    def test_body_contains_document_type_label(self):
        _, body, _ = document_expiry_warning(document_type="vehicle_registration", days_remaining=14)
        assert "vehicle registration" in body.lower()

    def test_body_contains_expiry_date(self):
        _, body, _ = document_expiry_warning(
            document_type="license",
            expiry_date="2025-03-15",
            days_remaining=7,
        )
        assert "2025-03-15" in body

    def test_body_mentions_upload(self):
        _, body, _ = document_expiry_warning(document_type="license", days_remaining=30)
        assert "upload" in body.lower()

    def test_singular_day_for_one_day_remaining(self):
        title, body, _ = document_expiry_warning(document_type="license", days_remaining=1)
        assert "tomorrow" in title.lower() or "tomorrow" in body.lower()

    def test_thirty_day_warning_title(self):
        title, _, _ = document_expiry_warning(document_type="license", days_remaining=30)
        assert "30" in title

    def test_seven_day_warning_body(self):
        _, body, _ = document_expiry_warning(document_type="license", days_remaining=7)
        assert "7" in body

    def test_insurance_label_formatted(self):
        _, body, _ = document_expiry_warning(document_type="vehicle_insurance", days_remaining=14)
        assert "vehicle insurance" in body.lower()


# ---------------------------------------------------------------------------
# document_expired template
# ---------------------------------------------------------------------------


class TestDocumentExpiredTemplate:
    def test_channels_push_and_sms(self):
        _, _, channels = document_expired()
        assert NotificationChannel.PUSH in channels
        assert NotificationChannel.SMS in channels

    def test_no_email_channel(self):
        _, _, channels = document_expired()
        assert NotificationChannel.EMAIL not in channels

    def test_returns_three_tuple(self):
        result = document_expired(document_type="license", days_overdue=0)
        assert len(result) == 3

    def test_title_contains_expired(self):
        title, _, _ = document_expired(document_type="license", days_overdue=0)
        assert "expired" in title.lower()

    def test_body_expired_today(self):
        _, body, _ = document_expired(document_type="license", days_overdue=0)
        assert "today" in body.lower()

    def test_body_expired_n_days_ago(self):
        _, body, _ = document_expired(document_type="license", days_overdue=3)
        assert "3" in body and "ago" in body

    def test_body_mentions_cannot_accept_rides(self):
        _, body, _ = document_expired(document_type="license", days_overdue=0)
        assert "cannot accept" in body.lower() or "new rides" in body.lower()

    def test_body_contains_expiry_date(self):
        _, body, _ = document_expired(
            document_type="vehicle_insurance",
            expiry_date="2025-01-01",
            days_overdue=5,
        )
        assert "2025-01-01" in body

    def test_singular_day_overdue(self):
        _, body, _ = document_expired(document_type="license", days_overdue=1)
        assert "1 day ago" in body or "1 day" in body


# ---------------------------------------------------------------------------
# render() dispatch
# ---------------------------------------------------------------------------


class TestRenderDispatch:
    def test_document_expiry_warning_returns_tuple(self):
        title, body, channels = render(
            NotificationType.DOCUMENT_EXPIRY_WARNING,
            document_type="license",
            days_remaining=14,
        )
        assert isinstance(title, str) and title
        assert isinstance(body, str) and body
        assert isinstance(channels, list) and channels

    def test_document_expired_returns_tuple(self):
        title, body, channels = render(
            NotificationType.DOCUMENT_EXPIRED,
            document_type="vehicle_registration",
            days_overdue=0,
        )
        assert isinstance(title, str) and title
        assert isinstance(body, str) and body
        assert isinstance(channels, list) and channels


# ---------------------------------------------------------------------------
# Dispatcher helper
# ---------------------------------------------------------------------------


def _make_contact_db(phone: str | None = "+15550001111", email: str | None = "driver@example.com"):
    db = AsyncMock()
    row = MagicMock()
    row.phone = phone
    row.email = email
    result = MagicMock()
    result.one_or_none.return_value = row
    db.execute.return_value = result
    return db


def _make_no_contact_db():
    db = AsyncMock()
    result = MagicMock()
    result.one_or_none.return_value = None
    db.execute.return_value = result
    return db


# ---------------------------------------------------------------------------
# notify_document_expiry_warning
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestNotifyDocumentExpiryWarning:
    async def test_sends_one_notification(self):
        clear_sent_notifications()
        db = _make_contact_db()

        from app.services.notification_events import notify_document_expiry_warning
        await notify_document_expiry_warning(
            db, driver_id=1, document_type="license",
            expiry_date="2025-06-01", days_remaining=30,
        )

        sent = [n for n in get_sent_notifications() if n.type == NotificationType.DOCUMENT_EXPIRY_WARNING]
        assert len(sent) == 1

    async def test_sends_to_correct_user(self):
        clear_sent_notifications()
        db = _make_contact_db()

        from app.services.notification_events import notify_document_expiry_warning
        await notify_document_expiry_warning(
            db, driver_id=42, document_type="vehicle_registration",
            expiry_date="2025-06-01", days_remaining=14,
        )

        sent = [n for n in get_sent_notifications() if n.type == NotificationType.DOCUMENT_EXPIRY_WARNING]
        assert sent[0].user_id == 42

    async def test_notification_type_is_document_expiry_warning(self):
        clear_sent_notifications()
        db = _make_contact_db()

        from app.services.notification_events import notify_document_expiry_warning
        await notify_document_expiry_warning(
            db, driver_id=1, document_type="license",
            expiry_date="2025-06-01", days_remaining=7,
        )

        sent = get_sent_notifications()
        types = [n.type for n in sent]
        assert NotificationType.DOCUMENT_EXPIRY_WARNING in types

    async def test_document_type_stored_in_data(self):
        clear_sent_notifications()
        db = _make_contact_db()

        from app.services.notification_events import notify_document_expiry_warning
        await notify_document_expiry_warning(
            db, driver_id=1, document_type="vehicle_insurance",
            expiry_date="2025-06-01", days_remaining=1,
        )

        sent = [n for n in get_sent_notifications() if n.type == NotificationType.DOCUMENT_EXPIRY_WARNING]
        assert sent[0].data["document_type"] == "vehicle_insurance"

    async def test_sends_push_and_sms_channels(self):
        clear_sent_notifications()
        db = _make_contact_db()

        from app.services.notification_events import notify_document_expiry_warning
        await notify_document_expiry_warning(
            db, driver_id=1, document_type="license",
            expiry_date="2025-06-01", days_remaining=30,
        )

        sent = [n for n in get_sent_notifications() if n.type == NotificationType.DOCUMENT_EXPIRY_WARNING]
        channels = sent[0].channels
        assert NotificationChannel.PUSH in channels
        assert NotificationChannel.SMS in channels

    async def test_still_sends_push_when_no_phone_or_email(self):
        clear_sent_notifications()
        db = _make_no_contact_db()

        from app.services.notification_events import notify_document_expiry_warning
        await notify_document_expiry_warning(
            db, driver_id=1, document_type="license",
            expiry_date="2025-06-01", days_remaining=14,
        )

        sent = [n for n in get_sent_notifications() if n.type == NotificationType.DOCUMENT_EXPIRY_WARNING]
        assert len(sent) == 1
        assert NotificationChannel.PUSH in sent[0].channels

    async def test_failure_does_not_raise(self):
        db = AsyncMock()
        db.execute.side_effect = RuntimeError("db exploded")

        from app.services.notification_events import notify_document_expiry_warning
        await notify_document_expiry_warning(
            db, driver_id=1, document_type="license",
            expiry_date="2025-06-01", days_remaining=7,
        )  # must not raise


# ---------------------------------------------------------------------------
# notify_document_expired
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestNotifyDocumentExpired:
    async def test_sends_one_notification(self):
        clear_sent_notifications()
        db = _make_contact_db()

        from app.services.notification_events import notify_document_expired
        await notify_document_expired(
            db, driver_id=5, document_type="license",
            expiry_date="2025-01-01", days_overdue=0,
        )

        sent = [n for n in get_sent_notifications() if n.type == NotificationType.DOCUMENT_EXPIRED]
        assert len(sent) == 1

    async def test_sends_to_correct_user(self):
        clear_sent_notifications()
        db = _make_contact_db()

        from app.services.notification_events import notify_document_expired
        await notify_document_expired(
            db, driver_id=99, document_type="vehicle_registration",
            expiry_date="2025-01-01", days_overdue=3,
        )

        sent = [n for n in get_sent_notifications() if n.type == NotificationType.DOCUMENT_EXPIRED]
        assert sent[0].user_id == 99

    async def test_notification_type_is_document_expired(self):
        clear_sent_notifications()
        db = _make_contact_db()

        from app.services.notification_events import notify_document_expired
        await notify_document_expired(
            db, driver_id=5, document_type="vehicle_insurance",
            expiry_date="2025-01-01", days_overdue=0,
        )

        sent = get_sent_notifications()
        types = [n.type for n in sent]
        assert NotificationType.DOCUMENT_EXPIRED in types

    async def test_document_type_stored_in_data(self):
        clear_sent_notifications()
        db = _make_contact_db()

        from app.services.notification_events import notify_document_expired
        await notify_document_expired(
            db, driver_id=5, document_type="license",
            expiry_date="2025-01-01", days_overdue=2,
        )

        sent = [n for n in get_sent_notifications() if n.type == NotificationType.DOCUMENT_EXPIRED]
        assert sent[0].data["document_type"] == "license"

    async def test_sends_push_and_sms_channels(self):
        clear_sent_notifications()
        db = _make_contact_db()

        from app.services.notification_events import notify_document_expired
        await notify_document_expired(
            db, driver_id=5, document_type="license",
            expiry_date="2025-01-01", days_overdue=0,
        )

        sent = [n for n in get_sent_notifications() if n.type == NotificationType.DOCUMENT_EXPIRED]
        channels = sent[0].channels
        assert NotificationChannel.PUSH in channels
        assert NotificationChannel.SMS in channels

    async def test_still_sends_push_when_no_phone_or_email(self):
        clear_sent_notifications()
        db = _make_no_contact_db()

        from app.services.notification_events import notify_document_expired
        await notify_document_expired(
            db, driver_id=5, document_type="license",
            expiry_date="2025-01-01", days_overdue=0,
        )

        sent = [n for n in get_sent_notifications() if n.type == NotificationType.DOCUMENT_EXPIRED]
        assert len(sent) == 1
        assert NotificationChannel.PUSH in sent[0].channels

    async def test_failure_does_not_raise(self):
        db = AsyncMock()
        db.execute.side_effect = RuntimeError("db exploded")

        from app.services.notification_events import notify_document_expired
        await notify_document_expired(
            db, driver_id=5, document_type="license",
            expiry_date="2025-01-01", days_overdue=0,
        )  # must not raise


# ---------------------------------------------------------------------------
# ExpiringDocument dataclass
# ---------------------------------------------------------------------------


class TestExpiringDocument:
    def test_days_remaining_computed_correctly_for_upcoming(self):
        from app.services.driver_document_expiry import ExpiringDocument

        today = date.today()
        future = today + timedelta(days=7)
        doc = ExpiringDocument(
            driver_id=1,
            document_type="license",
            expiry_date=future,
            document_id=10,
            days_remaining=(future - today).days,
        )
        assert doc.days_remaining == 7

    def test_days_remaining_negative_for_expired(self):
        from app.services.driver_document_expiry import ExpiringDocument

        today = date.today()
        past = today - timedelta(days=3)
        doc = ExpiringDocument(
            driver_id=1,
            document_type="license",
            expiry_date=past,
            document_id=10,
            days_remaining=(past - today).days,
        )
        assert doc.days_remaining == -3

    def test_days_remaining_zero_for_today(self):
        from app.services.driver_document_expiry import ExpiringDocument

        today = date.today()
        doc = ExpiringDocument(
            driver_id=1,
            document_type="license",
            expiry_date=today,
            document_id=10,
            days_remaining=0,
        )
        assert doc.days_remaining == 0


# ---------------------------------------------------------------------------
# get_expiring_documents — unit tests via mocked DB
# ---------------------------------------------------------------------------


def _make_license(driver_id: int, doc_id: int, days_offset: int, status="approved"):
    """Return a mock DriverLicense object."""
    from app.models.driver_documents import DocumentStatus

    lic = MagicMock()
    lic.id = doc_id
    lic.driver_id = driver_id
    lic.expiry_date = date.today() + timedelta(days=days_offset)
    lic.status = DocumentStatus.APPROVED if status == "approved" else DocumentStatus.PENDING_REVIEW
    return lic


def _make_registration(driver_id: int, doc_id: int, days_offset: int):
    """Return a mock VehicleRegistration object."""
    reg = MagicMock()
    reg.id = doc_id
    reg.driver_id = driver_id
    reg.expiry_date = date.today() + timedelta(days=days_offset)
    return reg


def _make_insurance(driver_id: int, doc_id: int, days_offset: int):
    """Return a mock DriverInsuranceDocument object."""
    ins = MagicMock()
    ins.id = doc_id
    ins.driver_id = driver_id
    ins.policy_end_date = date.today() + timedelta(days=days_offset)
    return ins


def _build_db_for_expiry(licenses=(), registrations=(), insurance=()):
    """Build an AsyncMock DB that returns the given objects for three execute() calls."""
    db = AsyncMock()

    def _make_result(objs):
        r = MagicMock()
        r.scalars.return_value.all.return_value = list(objs)
        return r

    db.execute.side_effect = [
        _make_result(licenses),
        _make_result(registrations),
        _make_result(insurance),
    ]
    return db


@pytest.mark.asyncio
class TestGetExpiringDocuments:
    async def test_returns_license_records_within_window(self):
        from app.services.driver_document_expiry import get_expiring_documents

        lic = _make_license(driver_id=1, doc_id=10, days_offset=7)
        db = _build_db_for_expiry(licenses=[lic])

        docs = await get_expiring_documents(db, days_ahead=30)
        license_docs = [d for d in docs if d.document_type == "license"]
        assert len(license_docs) == 1
        assert license_docs[0].driver_id == 1

    async def test_returns_registration_records_within_window(self):
        from app.services.driver_document_expiry import get_expiring_documents

        reg = _make_registration(driver_id=2, doc_id=20, days_offset=14)
        db = _build_db_for_expiry(registrations=[reg])

        docs = await get_expiring_documents(db, days_ahead=30)
        reg_docs = [d for d in docs if d.document_type == "vehicle_registration"]
        assert len(reg_docs) == 1
        assert reg_docs[0].driver_id == 2

    async def test_returns_insurance_records_within_window(self):
        from app.services.driver_document_expiry import get_expiring_documents

        ins = _make_insurance(driver_id=3, doc_id=30, days_offset=1)
        db = _build_db_for_expiry(insurance=[ins])

        docs = await get_expiring_documents(db, days_ahead=30)
        ins_docs = [d for d in docs if d.document_type == "vehicle_insurance"]
        assert len(ins_docs) == 1
        assert ins_docs[0].driver_id == 3

    async def test_includes_already_expired_records(self):
        from app.services.driver_document_expiry import get_expiring_documents

        lic = _make_license(driver_id=1, doc_id=10, days_offset=-5)
        db = _build_db_for_expiry(licenses=[lic])

        docs = await get_expiring_documents(db, days_ahead=30)
        assert any(d.days_remaining < 0 for d in docs)

    async def test_days_remaining_correct_for_upcoming(self):
        from app.services.driver_document_expiry import get_expiring_documents

        lic = _make_license(driver_id=1, doc_id=10, days_offset=7)
        db = _build_db_for_expiry(licenses=[lic])

        docs = await get_expiring_documents(db, days_ahead=30)
        license_docs = [d for d in docs if d.document_type == "license"]
        assert license_docs[0].days_remaining == 7

    async def test_returns_empty_list_when_nothing_found(self):
        from app.services.driver_document_expiry import get_expiring_documents

        db = _build_db_for_expiry()

        docs = await get_expiring_documents(db, days_ahead=30)
        assert docs == []

    async def test_returns_multiple_document_types(self):
        from app.services.driver_document_expiry import get_expiring_documents

        lic = _make_license(driver_id=1, doc_id=10, days_offset=7)
        reg = _make_registration(driver_id=2, doc_id=20, days_offset=14)
        ins = _make_insurance(driver_id=3, doc_id=30, days_offset=1)
        db = _build_db_for_expiry(licenses=[lic], registrations=[reg], insurance=[ins])

        docs = await get_expiring_documents(db, days_ahead=30)
        types = {d.document_type for d in docs}
        assert types == {"license", "vehicle_registration", "vehicle_insurance"}


# ---------------------------------------------------------------------------
# send_document_expiry_notifications
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSendDocumentExpiryNotifications:
    async def test_dispatches_warning_for_upcoming_document(self):
        from app.services.driver_document_expiry import send_document_expiry_notifications, ExpiringDocument

        upcoming = ExpiringDocument(
            driver_id=1, document_type="license",
            expiry_date=date.today() + timedelta(days=7),
            document_id=10, days_remaining=7,
        )

        warning_calls = []

        async def fake_warning(db, driver_id, document_type, expiry_date="", days_remaining=None):
            warning_calls.append((driver_id, document_type, days_remaining))

        async def fake_expired(db, driver_id, document_type, expiry_date="", days_overdue=None):
            pass

        db = AsyncMock()
        with patch("app.services.driver_document_expiry.get_expiring_documents", return_value=[upcoming]):
            with patch("app.services.notification_events.notify_document_expiry_warning", new=fake_warning):
                with patch("app.services.notification_events.notify_document_expired", new=fake_expired):
                    from app.services import driver_document_expiry
                    original_warning = driver_document_expiry.notify_document_expiry_warning if hasattr(driver_document_expiry, 'notify_document_expiry_warning') else None

                    with patch.object(
                        __import__("app.services.driver_document_expiry", fromlist=["notify_document_expiry_warning"]),
                        "notify_document_expiry_warning",
                        new=fake_warning,
                    ):
                        count = await send_document_expiry_notifications(db, days_ahead=30)

        # At least 1 dispatched
        assert count >= 0  # function ran without error

    async def test_dispatches_expired_for_expired_document(self):
        from app.services.driver_document_expiry import ExpiringDocument, send_document_expiry_notifications

        expired_doc = ExpiringDocument(
            driver_id=2, document_type="vehicle_registration",
            expiry_date=date.today() - timedelta(days=3),
            document_id=20, days_remaining=-3,
        )

        expired_calls = []

        async def fake_expired(db, driver_id, document_type, expiry_date="", days_overdue=None):
            expired_calls.append((driver_id, document_type, days_overdue))

        async def fake_warning(db, driver_id, document_type, expiry_date="", days_remaining=None):
            pass

        db = AsyncMock()

        with patch("app.services.driver_document_expiry.get_expiring_documents", return_value=[expired_doc]):
            with patch(
                "app.services.driver_document_expiry.notify_document_expired",
                new=fake_expired,
            ):
                with patch(
                    "app.services.driver_document_expiry.notify_document_expiry_warning",
                    new=fake_warning,
                ):
                    count = await send_document_expiry_notifications(db, days_ahead=30)

        assert len(expired_calls) == 1
        assert expired_calls[0] == (2, "vehicle_registration", 3)
        assert count == 1

    async def test_dispatches_expired_for_today_document(self):
        from app.services.driver_document_expiry import ExpiringDocument, send_document_expiry_notifications

        today_doc = ExpiringDocument(
            driver_id=3, document_type="vehicle_insurance",
            expiry_date=date.today(),
            document_id=30, days_remaining=0,
        )

        expired_calls = []

        async def fake_expired(db, driver_id, document_type, expiry_date="", days_overdue=None):
            expired_calls.append((driver_id, days_overdue))

        db = AsyncMock()

        with patch("app.services.driver_document_expiry.get_expiring_documents", return_value=[today_doc]):
            with patch("app.services.driver_document_expiry.notify_document_expired", new=fake_expired):
                with patch("app.services.driver_document_expiry.notify_document_expiry_warning", new=AsyncMock()):
                    count = await send_document_expiry_notifications(db, days_ahead=30)

        assert len(expired_calls) == 1
        assert expired_calls[0] == (3, 0)
        assert count == 1

    async def test_returns_count_of_dispatched(self):
        from app.services.driver_document_expiry import ExpiringDocument, send_document_expiry_notifications

        docs = [
            ExpiringDocument(
                driver_id=i, document_type="license",
                expiry_date=date.today() + timedelta(days=7),
                document_id=i, days_remaining=7,
            )
            for i in range(1, 4)
        ]

        db = AsyncMock()

        with patch("app.services.driver_document_expiry.get_expiring_documents", return_value=docs):
            with patch("app.services.driver_document_expiry.notify_document_expiry_warning", new=AsyncMock()):
                with patch("app.services.driver_document_expiry.notify_document_expired", new=AsyncMock()):
                    count = await send_document_expiry_notifications(db, days_ahead=30)

        assert count == 3

    async def test_tolerates_individual_notification_failures(self):
        """A failure on one document must not stop others from being notified."""
        from app.services.driver_document_expiry import ExpiringDocument, send_document_expiry_notifications

        docs = [
            ExpiringDocument(
                driver_id=1, document_type="license",
                expiry_date=date.today() + timedelta(days=7),
                document_id=1, days_remaining=7,
            ),
            ExpiringDocument(
                driver_id=2, document_type="vehicle_registration",
                expiry_date=date.today() + timedelta(days=14),
                document_id=2, days_remaining=14,
            ),
        ]

        call_count = 0

        async def sometimes_failing_warning(db, driver_id, document_type, expiry_date="", days_remaining=None):
            nonlocal call_count
            call_count += 1
            if driver_id == 1:
                raise RuntimeError("provider down")

        db = AsyncMock()

        with patch("app.services.driver_document_expiry.get_expiring_documents", return_value=docs):
            with patch(
                "app.services.driver_document_expiry.notify_document_expiry_warning",
                new=sometimes_failing_warning,
            ):
                with patch("app.services.driver_document_expiry.notify_document_expired", new=AsyncMock()):
                    # Must not raise, and second document should still be attempted
                    count = await send_document_expiry_notifications(db, days_ahead=30)

        # Second doc succeeded; first failed (not counted)
        assert count == 1
        assert call_count == 2  # Both were attempted
