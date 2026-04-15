"""Unit tests for the GDPR/CCPA Privacy Compliance feature.

Service layer (unit tests — all pass without a live DB):
  1.  record_consent — creates a new record
  2.  record_consent — upserts when record already exists
  3.  get_user_consents — returns list ordered by date
  4.  request_data_export — creates PENDING request
  5.  request_data_export — raises ValueError if export already in progress
  6.  get_export_request — returns record when owned by user
  7.  get_export_request — returns None when not found
  8.  generate_user_data_export — returns correct structure with all keys
  9.  complete_export_request — sets READY status and expiry
  10. mark_export_downloaded — increments download_count
  11. mark_export_downloaded — sets DOWNLOADED at count >= 3
  12. request_account_deletion — creates PENDING deletion request
  13. request_account_deletion — raises ValueError if deletion already pending
  14. cancel_deletion_request — cancels successfully
  15. cancel_deletion_request — raises ValueError("not_found") for wrong owner
  16. cancel_deletion_request — raises ValueError("cannot_cancel") for bad status
  17. execute_account_deletion — anonymises user PII fields
  18. execute_account_deletion — returns True
  19. get_deletion_request — returns latest non-cancelled request
  20. get_deletion_request — returns None when no active request

API layer (TestClient with dependency overrides):
  21. POST /privacy/consents — 200 success
  22. POST /privacy/data-export — 201 success
  23. POST /privacy/data-export — 409 when already in progress
  24. GET /privacy/data-export/{id} — 200 with record data
  25. GET /privacy/data-export/{id}/download — 200 with export data
  26. POST /privacy/delete-account — 201 success
  27. DELETE /privacy/delete-account/{id} — 200 cancels request
  28. GET /privacy/admin/exports — 200 admin list
  29. GET /privacy/admin/deletions — 200 admin list
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.privacy import (
    AccountDeletionRequest,
    DataExportRequest,
    DeletionStatus,
    ExportStatus,
    PolicyType,
    PrivacyConsentRecord,
)
from app.schemas.privacy import (
    ConsentRecordResponse,
    DataExportRequestResponse,
    DeletionRequestResponse,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)


def _make_consent(**kwargs) -> PrivacyConsentRecord:
    defaults = dict(
        id=1,
        user_id=10,
        policy_type=PolicyType.PRIVACY_POLICY,
        policy_version="1.0",
        consented=True,
        ip_address="127.0.0.1",
        user_agent="pytest",
        consented_at=_NOW,
    )
    defaults.update(kwargs)
    obj = MagicMock(spec=PrivacyConsentRecord)
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _make_export(**kwargs) -> DataExportRequest:
    defaults = dict(
        id=1,
        user_id=10,
        status=ExportStatus.PENDING,
        requested_at=_NOW,
        completed_at=None,
        expires_at=None,
        download_count=0,
        error_message=None,
    )
    defaults.update(kwargs)
    obj = MagicMock(spec=DataExportRequest)
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _make_deletion(**kwargs) -> AccountDeletionRequest:
    defaults = dict(
        id=1,
        user_id=10,
        status=DeletionStatus.PENDING,
        reason=None,
        requested_at=_NOW,
        scheduled_for=_NOW + timedelta(days=30),
        completed_at=None,
        cancelled_at=None,
    )
    defaults.update(kwargs)
    obj = MagicMock(spec=AccountDeletionRequest)
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _make_db():
    """Build a synchronous MagicMock for SQLAlchemy Session."""
    db = MagicMock()
    db.add = MagicMock()
    db.commit = MagicMock()
    db.refresh = MagicMock()
    return db


# ---------------------------------------------------------------------------
# 1–3 record_consent / get_user_consents
# ---------------------------------------------------------------------------


def test_record_consent_creates_new():
    """New consent record is added and committed."""
    from app.services.privacy import record_consent

    db = _make_db()
    # query().filter().first() returns None → new record
    db.query.return_value.filter.return_value.first.return_value = None

    result = record_consent(
        db,
        user_id=10,
        policy_type=PolicyType.PRIVACY_POLICY,
        policy_version="1.0",
        consented=True,
    )

    db.add.assert_called_once()
    db.commit.assert_called_once()
    db.refresh.assert_called_once()


def test_record_consent_upserts_existing():
    """Existing record is updated, not duplicated."""
    from app.services.privacy import record_consent

    existing = _make_consent(consented=False)
    db = _make_db()
    db.query.return_value.filter.return_value.first.return_value = existing

    record_consent(
        db,
        user_id=10,
        policy_type=PolicyType.PRIVACY_POLICY,
        policy_version="1.0",
        consented=True,
        ip_address="10.0.0.1",
    )

    db.add.assert_not_called()
    db.commit.assert_called_once()
    assert existing.consented is True
    assert existing.ip_address == "10.0.0.1"


def test_get_user_consents_returns_list():
    """Returns the list from the query chain."""
    from app.services.privacy import get_user_consents

    records = [_make_consent(), _make_consent(id=2)]
    db = _make_db()
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = records

    result = get_user_consents(db, user_id=10)
    assert result == records


# ---------------------------------------------------------------------------
# 4–5 request_data_export
# ---------------------------------------------------------------------------


def test_request_data_export_creates_pending():
    """Creates a new PENDING export request."""
    from app.services.privacy import request_data_export

    db = _make_db()
    # No in-progress request
    db.query.return_value.filter.return_value.filter.return_value.first.return_value = None
    db.query.return_value.filter.return_value.first.return_value = None

    result = request_data_export(db, user_id=10)

    db.add.assert_called_once()
    db.commit.assert_called_once()


def test_request_data_export_raises_if_in_progress():
    """ValueError('export_in_progress') when a PENDING/PROCESSING request exists."""
    from app.services.privacy import request_data_export

    existing = _make_export(status=ExportStatus.PENDING)
    db = _make_db()

    # chain: query(DataExportRequest).filter(...).filter(...).first()
    # We need to make the in-progress check return a record
    q = MagicMock()
    q.filter.return_value.filter.return_value.first.return_value = existing
    q.filter.return_value.first.return_value = existing
    db.query.return_value = q

    with pytest.raises(ValueError, match="export_in_progress"):
        request_data_export(db, user_id=10)


# ---------------------------------------------------------------------------
# 6–7 get_export_request
# ---------------------------------------------------------------------------


def test_get_export_request_found():
    """Returns record when it exists and belongs to the user."""
    from app.services.privacy import get_export_request

    record = _make_export()
    db = _make_db()
    # Service uses a single .filter() with multiple conditions
    db.query.return_value.filter.return_value.first.return_value = record

    result = get_export_request(db, request_id=1, user_id=10)
    assert result is record


def test_get_export_request_not_found():
    """Returns None when record is not found."""
    from app.services.privacy import get_export_request

    db = _make_db()
    # Service uses a single .filter() with multiple conditions
    db.query.return_value.filter.return_value.first.return_value = None

    result = get_export_request(db, request_id=999, user_id=10)
    assert result is None


# ---------------------------------------------------------------------------
# 8 generate_user_data_export
# ---------------------------------------------------------------------------


def test_generate_user_data_export_structure():
    """Returns a dict with the required top-level keys."""
    from app.services.privacy import generate_user_data_export

    db = _make_db()

    # Mock user
    mock_user = MagicMock()
    mock_user.id = 10
    mock_user.name = "Alice"
    mock_user.email = "alice@example.com"
    mock_user.phone = "+15551234567"
    mock_user.role.value = "rider"
    mock_user.created_at = _NOW

    # The chain for user lookup: query(User).filter().first()
    # For consents: query(PrivacyConsentRecord).filter().order_by().all()
    def query_side_effect(model):
        q = MagicMock()
        name = getattr(model, "__name__", str(model))
        if "User" in name:
            q.filter.return_value.first.return_value = mock_user
        elif "PrivacyConsentRecord" in name:
            q.filter.return_value.order_by.return_value.all.return_value = []
        else:
            q.filter.return_value.count.return_value = 0
        return q

    db.query.side_effect = query_side_effect

    with patch("app.services.privacy.get_user_consents", return_value=[]):
        result = generate_user_data_export(db, user_id=10)

    assert "profile" in result
    assert "ride_count" in result
    assert "payment_count" in result
    assert "consents" in result
    assert isinstance(result["consents"], list)


# ---------------------------------------------------------------------------
# 9 complete_export_request
# ---------------------------------------------------------------------------


def test_complete_export_request_sets_ready():
    """Sets status=READY and populates completed_at/expires_at."""
    from app.services.privacy import complete_export_request

    record = _make_export(status=ExportStatus.PROCESSING)
    db = _make_db()
    db.query.return_value.filter.return_value.first.return_value = record

    complete_export_request(db, request_id=1)

    assert record.status == ExportStatus.READY
    assert record.completed_at is not None
    assert record.expires_at is not None
    db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# 10–11 mark_export_downloaded
# ---------------------------------------------------------------------------


def test_mark_export_downloaded_increments_count():
    """Increments download_count by 1."""
    from app.services.privacy import mark_export_downloaded

    record = _make_export(status=ExportStatus.READY, download_count=0)
    db = _make_db()
    db.query.return_value.filter.return_value.first.return_value = record

    mark_export_downloaded(db, request_id=1)

    assert record.download_count == 1
    db.commit.assert_called_once()


def test_mark_export_downloaded_sets_downloaded_at_three():
    """Status becomes DOWNLOADED when download_count reaches 3."""
    from app.services.privacy import mark_export_downloaded

    record = _make_export(status=ExportStatus.READY, download_count=2)
    db = _make_db()
    db.query.return_value.filter.return_value.first.return_value = record

    mark_export_downloaded(db, request_id=1)

    assert record.download_count == 3
    assert record.status == ExportStatus.DOWNLOADED


# ---------------------------------------------------------------------------
# 12–13 request_account_deletion
# ---------------------------------------------------------------------------


def test_request_account_deletion_creates_pending():
    """Creates a PENDING deletion request with scheduled_for = now + 30 days."""
    from app.services.privacy import request_account_deletion

    db = _make_db()
    db.query.return_value.filter.return_value.filter.return_value.first.return_value = None
    db.query.return_value.filter.return_value.first.return_value = None

    result = request_account_deletion(db, user_id=10, reason="Closing account")

    db.add.assert_called_once()
    db.commit.assert_called_once()


def test_request_account_deletion_raises_if_pending():
    """ValueError('deletion_pending') when active deletion request exists."""
    from app.services.privacy import request_account_deletion

    existing = _make_deletion(status=DeletionStatus.PENDING)
    db = _make_db()

    q = MagicMock()
    q.filter.return_value.filter.return_value.first.return_value = existing
    q.filter.return_value.first.return_value = existing
    db.query.return_value = q

    with pytest.raises(ValueError, match="deletion_pending"):
        request_account_deletion(db, user_id=10)


# ---------------------------------------------------------------------------
# 14–16 cancel_deletion_request
# ---------------------------------------------------------------------------


def test_cancel_deletion_request_success():
    """Cancels a PENDING deletion request."""
    from app.services.privacy import cancel_deletion_request

    record = _make_deletion(user_id=10, status=DeletionStatus.PENDING)
    db = _make_db()
    db.query.return_value.filter.return_value.first.return_value = record

    cancel_deletion_request(db, request_id=1, user_id=10)

    assert record.status == DeletionStatus.CANCELLED
    assert record.cancelled_at is not None
    db.commit.assert_called_once()


def test_cancel_deletion_request_wrong_owner():
    """ValueError('not_found') if user doesn't own the request."""
    from app.services.privacy import cancel_deletion_request

    record = _make_deletion(user_id=99, status=DeletionStatus.PENDING)
    db = _make_db()
    db.query.return_value.filter.return_value.first.return_value = record

    with pytest.raises(ValueError, match="not_found"):
        cancel_deletion_request(db, request_id=1, user_id=10)


def test_cancel_deletion_request_terminal_status():
    """ValueError('cannot_cancel') if request is COMPLETED."""
    from app.services.privacy import cancel_deletion_request

    record = _make_deletion(user_id=10, status=DeletionStatus.COMPLETED)
    db = _make_db()
    db.query.return_value.filter.return_value.first.return_value = record

    with pytest.raises(ValueError, match="cannot_cancel"):
        cancel_deletion_request(db, request_id=1, user_id=10)


# ---------------------------------------------------------------------------
# 17–18 execute_account_deletion
# ---------------------------------------------------------------------------


def test_execute_account_deletion_anonymises_pii():
    """Overwrites name, email, phone, password_hash; deactivates account."""
    from app.services.privacy import execute_account_deletion
    from app.models.user import User

    mock_user = MagicMock(spec=User)
    mock_user.id = 10

    db = _make_db()

    def query_side(model):
        q = MagicMock()
        if model is User:
            q.filter.return_value.first.return_value = mock_user
        else:
            q.filter.return_value.filter.return_value.all.return_value = []
        return q

    db.query.side_effect = query_side

    execute_account_deletion(db, user_id=10)

    assert mock_user.name == "Deleted User 10"
    assert mock_user.email is None
    assert mock_user.phone == "+0000010"
    assert mock_user.password_hash == ""
    assert mock_user.is_active is False


def test_execute_account_deletion_returns_true():
    """Returns True regardless of whether a user row exists."""
    from app.services.privacy import execute_account_deletion
    from app.models.user import User

    db = _make_db()

    def query_side(model):
        q = MagicMock()
        if model is User:
            q.filter.return_value.first.return_value = None
        else:
            q.filter.return_value.filter.return_value.all.return_value = []
        return q

    db.query.side_effect = query_side

    result = execute_account_deletion(db, user_id=10)
    assert result is True


# ---------------------------------------------------------------------------
# 19–20 get_deletion_request
# ---------------------------------------------------------------------------


def test_get_deletion_request_found():
    """Returns the most recent non-cancelled deletion request."""
    from app.services.privacy import get_deletion_request

    record = _make_deletion()
    db = _make_db()
    # Service uses a single .filter() with multiple conditions
    (
        db.query.return_value
        .filter.return_value
        .order_by.return_value
        .first.return_value
    ) = record

    result = get_deletion_request(db, user_id=10)
    assert result is record


def test_get_deletion_request_not_found():
    """Returns None when no active deletion request exists."""
    from app.services.privacy import get_deletion_request

    db = _make_db()
    # Service uses a single .filter() with multiple conditions
    (
        db.query.return_value
        .filter.return_value
        .order_by.return_value
        .first.return_value
    ) = None

    result = get_deletion_request(db, user_id=10)
    assert result is None


# ---------------------------------------------------------------------------
# 21–29 API layer (dependency-override TestClient)
# ---------------------------------------------------------------------------


def _make_api_user(role: str = "rider") -> MagicMock:
    user = MagicMock()
    user.id = 10
    user.role = MagicMock()
    user.role.value = role
    user.is_active = True
    return user


def _make_api_db():
    db = MagicMock()
    db.add = MagicMock()
    db.commit = MagicMock()
    db.refresh = MagicMock()
    return db


@pytest.fixture
def api_client():
    """Synchronous TestClient with mocked auth and DB."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    user = _make_api_user()
    db = _make_api_db()

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db

    client = TestClient(app, raise_server_exceptions=False)
    yield client, user, db

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def admin_client():
    """Synchronous TestClient with mocked admin auth and DB."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, require_admin, get_db

    user = _make_api_user(role="admin")
    db = _make_api_db()

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[require_admin] = lambda: user
    app.dependency_overrides[get_db] = lambda: db

    client = TestClient(app, raise_server_exceptions=False)
    yield client, user, db

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(require_admin, None)
    app.dependency_overrides.pop(get_db, None)


def test_api_post_consent_200(api_client):
    """POST /privacy/consents returns 200 with consent record."""
    client, user, db = api_client
    record = _make_consent()

    with patch("app.services.privacy.record_consent", return_value=record):
        resp = client.post(
            "/api/v1/privacy/consents",
            json={
                "policy_type": "PRIVACY_POLICY",
                "policy_version": "1.0",
                "consented": True,
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["policy_type"] == "PRIVACY_POLICY"


def test_api_post_data_export_201(api_client):
    """POST /privacy/data-export returns 201."""
    client, user, db = api_client
    record = _make_export()

    with patch("app.services.privacy.request_data_export", return_value=record):
        resp = client.post("/api/v1/privacy/data-export")

    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "PENDING"


def test_api_post_data_export_409_in_progress(api_client):
    """POST /privacy/data-export returns 409 when export already in progress."""
    client, user, db = api_client

    with patch(
        "app.services.privacy.request_data_export",
        side_effect=ValueError("export_in_progress"),
    ):
        resp = client.post("/api/v1/privacy/data-export")

    assert resp.status_code == 409


def test_api_get_export_status_200(api_client):
    """GET /privacy/data-export/{id} returns 200."""
    client, user, db = api_client
    record = _make_export()

    with patch("app.services.privacy.get_export_request", return_value=record):
        resp = client.get("/api/v1/privacy/data-export/1")

    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data


def test_api_download_export_200(api_client):
    """GET /privacy/data-export/{id}/download returns 200 with export data."""
    client, user, db = api_client
    record = _make_export(status=ExportStatus.READY)
    export_data = {
        "profile": {"id": 10},
        "ride_count": 5,
        "payment_count": 3,
        "consents": [],
    }

    with patch("app.services.privacy.get_export_request", return_value=record):
        with patch("app.services.privacy.generate_user_data_export", return_value=export_data):
            with patch("app.services.privacy.mark_export_downloaded", return_value=record):
                resp = client.get("/api/v1/privacy/data-export/1/download")

    assert resp.status_code == 200
    data = resp.json()
    assert "profile" in data
    assert "ride_count" in data


def test_api_post_delete_account_201(api_client):
    """POST /privacy/delete-account returns 201."""
    client, user, db = api_client
    record = _make_deletion()

    with patch("app.services.privacy.request_account_deletion", return_value=record):
        resp = client.post("/api/v1/privacy/delete-account", json={})

    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "PENDING"


def test_api_cancel_deletion_200(api_client):
    """DELETE /privacy/delete-account/{id} returns 200."""
    client, user, db = api_client
    record = _make_deletion(status=DeletionStatus.CANCELLED)

    with patch("app.services.privacy.cancel_deletion_request", return_value=record):
        resp = client.delete("/api/v1/privacy/delete-account/1")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "CANCELLED"


def test_api_admin_list_exports_200(admin_client):
    """GET /privacy/admin/exports returns 200 for admin."""
    client, user, db = admin_client
    records = [_make_export()]

    with patch("app.services.privacy.get_all_export_requests", return_value=records):
        resp = client.get("/api/v1/privacy/admin/exports")

    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_api_admin_list_deletions_200(admin_client):
    """GET /privacy/admin/deletions returns 200 for admin."""
    client, user, db = admin_client
    records = [_make_deletion()]

    with patch("app.services.privacy.get_all_deletion_requests", return_value=records):
        resp = client.get("/api/v1/privacy/admin/deletions")

    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
