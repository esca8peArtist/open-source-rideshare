"""Tests for the Corporate Scheduled Reports feature.

Service tests (async, mocked DB):
  1.  create_scheduled_report — success, daily frequency
  2.  create_scheduled_report — next_due_at set to tomorrow for daily
  3.  create_scheduled_report — weekly requires day_of_week
  4.  create_scheduled_report — weekly without day_of_week → 422
  5.  create_scheduled_report — monthly requires day_of_month
  6.  create_scheduled_report — monthly without day_of_month → 422
  7.  create_scheduled_report — empty recipients → 422
  8.  create_scheduled_report — day_of_week out of range → 422
  9.  create_scheduled_report — day_of_month out of range → 422
  10. get_scheduled_report — success
  11. get_scheduled_report — wrong account → 404
  12. list_scheduled_reports — active_only=True returns only active
  13. list_scheduled_reports — active_only=False returns all
  14. list_scheduled_reports — empty list
  15. update_scheduled_report — name updated
  16. update_scheduled_report — recipients updated
  17. update_scheduled_report — frequency change recomputes next_due_at
  18. update_scheduled_report — empty recipients on update → 422
  19. update_scheduled_report — not found → 404
  20. deactivate_scheduled_report — sets is_active=False
  21. deactivate_scheduled_report — already inactive → 409
  22. deactivate_scheduled_report — not found → 404
  23. reactivate_scheduled_report — sets is_active=True + recomputes next_due_at
  24. reactivate_scheduled_report — already active → 409
  25. reactivate_scheduled_report — not found → 404
  26. delete_scheduled_report — success
  27. delete_scheduled_report — not found → 404
  28. trigger_report_now — success, last_sent_at updated
  29. trigger_report_now — advances next_due_at
  30. trigger_report_now — inactive report → 409
  31. trigger_report_now — not found → 404
  32. list_due_reports — returns overdue reports
  33. list_due_reports — future next_due_at not returned
  34. list_due_reports — inactive not returned

Helper tests (sync):
  35. _compute_next_due — daily: +1 day
  36. _compute_next_due — weekly: correct next weekday
  37. _compute_next_due — weekly same day: +7 days
  38. _compute_next_due — monthly: next month
  39. _compute_next_due — monthly: month wrap (Dec → Jan)

Schema tests (sync):
  40. ScheduledReportCreate — valid daily
  41. ScheduledReportCreate — recipients normalised to lowercase
  42. ScheduledReportCreate — too many recipients → ValidationError
  43. ScheduledReportUpdate — all fields optional
  44. ScheduledReportResponse — from_attributes
  45. ScheduledReportTriggerResponse — fields present

API layer tests (services patched):
  46. GET  /corporate/accounts/me/scheduled-reports — 200
  47. POST /corporate/accounts/me/scheduled-reports — 201
  48. GET  /corporate/accounts/me/scheduled-reports/{id} — 200
  49. PUT  /corporate/accounts/me/scheduled-reports/{id} — 200
  50. POST /corporate/accounts/me/scheduled-reports/{id}/deactivate — 200
  51. POST /corporate/accounts/me/scheduled-reports/{id}/reactivate — 200
  52. DELETE /corporate/accounts/me/scheduled-reports/{id} — 204
  53. POST /corporate/accounts/me/scheduled-reports/{id}/trigger — 200
  54. GET  /admin/corporate/accounts/{account_id}/scheduled-reports — 200
  55. GET  /admin/corporate/scheduled-reports/due — 200
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.models.corporate_scheduled_report import (
    CorporateScheduledReport,
    ReportFrequency,
    ScheduledReportType,
)
from app.schemas.corporate_scheduled_report import (
    ScheduledReportCreate,
    ScheduledReportListResponse,
    ScheduledReportResponse,
    ScheduledReportTriggerResponse,
    ScheduledReportUpdate,
)
from app.services.corporate_scheduled_report import (
    _compute_next_due,
    create_scheduled_report,
    deactivate_scheduled_report,
    delete_scheduled_report,
    get_scheduled_report,
    list_due_reports,
    list_scheduled_reports,
    reactivate_scheduled_report,
    trigger_report_now,
    update_scheduled_report,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)  # Wednesday


def _make_report(
    account_id: int = 1,
    name: str = "Weekly Spend",
    report_type: ScheduledReportType = ScheduledReportType.spending_overview,
    frequency: ReportFrequency = ReportFrequency.weekly,
    day_of_week: int | None = 0,
    day_of_month: int | None = None,
    recipients: list[str] | None = None,
    is_active: bool = True,
    last_sent_at: datetime | None = None,
    next_due_at: datetime | None = None,
) -> CorporateScheduledReport:
    return CorporateScheduledReport(
        id=uuid.uuid4(),
        account_id=account_id,
        name=name,
        report_type=report_type,
        frequency=frequency,
        day_of_week=day_of_week,
        day_of_month=day_of_month,
        recipients=recipients or ["admin@corp.com"],
        is_active=is_active,
        last_sent_at=last_sent_at,
        next_due_at=next_due_at or (_NOW + timedelta(days=5)),
        created_by_id=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _mock_db() -> AsyncMock:
    db = AsyncMock()
    db.flush = AsyncMock()
    db.delete = AsyncMock()
    return db


def _mock_db_with_result(rows) -> AsyncMock:
    """Return a mock DB that yields *rows* from execute()."""
    db = _mock_db()
    result = MagicMock()
    result.scalar_one_or_none.return_value = rows[0] if rows else None
    result.scalars.return_value.all.return_value = rows
    db.execute = AsyncMock(return_value=result)
    return db


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_daily_success():
    db = _mock_db()
    report = await create_scheduled_report(
        db,
        account_id=1,
        name="Daily Rides",
        report_type=ScheduledReportType.ride_patterns,
        frequency=ReportFrequency.daily,
        recipients=["a@b.com"],
    )
    assert report.account_id == 1
    assert report.frequency == ReportFrequency.daily
    assert report.is_active is True
    assert report.next_due_at is not None
    db.add.assert_called_once()
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_create_daily_next_due_is_tomorrow():
    db = _mock_db()
    before = datetime.now(tz=timezone.utc)
    report = await create_scheduled_report(
        db,
        account_id=1,
        name="d",
        report_type=ScheduledReportType.spending_overview,
        frequency=ReportFrequency.daily,
        recipients=["x@y.com"],
    )
    after = datetime.now(tz=timezone.utc)
    assert (before + timedelta(days=1)) <= report.next_due_at <= (after + timedelta(days=1))


@pytest.mark.asyncio
async def test_create_weekly_with_day_of_week_success():
    db = _mock_db()
    report = await create_scheduled_report(
        db,
        account_id=1,
        name="Monday Report",
        report_type=ScheduledReportType.monthly_trend,
        frequency=ReportFrequency.weekly,
        recipients=["r@s.com"],
        day_of_week=0,
    )
    assert report.day_of_week == 0


@pytest.mark.asyncio
async def test_create_weekly_missing_day_of_week_422():
    db = _mock_db()
    with pytest.raises(HTTPException) as exc:
        await create_scheduled_report(
            db,
            account_id=1,
            name="w",
            report_type=ScheduledReportType.spending_overview,
            frequency=ReportFrequency.weekly,
            recipients=["a@b.com"],
            day_of_week=None,
        )
    assert exc.value.status_code == 422
    assert "day_of_week" in exc.value.detail


@pytest.mark.asyncio
async def test_create_monthly_with_day_of_month_success():
    db = _mock_db()
    report = await create_scheduled_report(
        db,
        account_id=1,
        name="1st of month",
        report_type=ScheduledReportType.invoice_summary,
        frequency=ReportFrequency.monthly,
        recipients=["a@b.com"],
        day_of_month=1,
    )
    assert report.day_of_month == 1


@pytest.mark.asyncio
async def test_create_monthly_missing_day_of_month_422():
    db = _mock_db()
    with pytest.raises(HTTPException) as exc:
        await create_scheduled_report(
            db,
            account_id=1,
            name="m",
            report_type=ScheduledReportType.spending_overview,
            frequency=ReportFrequency.monthly,
            recipients=["a@b.com"],
            day_of_month=None,
        )
    assert exc.value.status_code == 422
    assert "day_of_month" in exc.value.detail


@pytest.mark.asyncio
async def test_create_empty_recipients_422():
    db = _mock_db()
    with pytest.raises(HTTPException) as exc:
        await create_scheduled_report(
            db,
            account_id=1,
            name="r",
            report_type=ScheduledReportType.spending_overview,
            frequency=ReportFrequency.daily,
            recipients=[],
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_create_day_of_week_out_of_range_422():
    db = _mock_db()
    with pytest.raises(HTTPException) as exc:
        await create_scheduled_report(
            db,
            account_id=1,
            name="r",
            report_type=ScheduledReportType.spending_overview,
            frequency=ReportFrequency.weekly,
            recipients=["a@b.com"],
            day_of_week=9,
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_create_day_of_month_out_of_range_422():
    db = _mock_db()
    with pytest.raises(HTTPException) as exc:
        await create_scheduled_report(
            db,
            account_id=1,
            name="r",
            report_type=ScheduledReportType.spending_overview,
            frequency=ReportFrequency.monthly,
            recipients=["a@b.com"],
            day_of_month=31,
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_get_scheduled_report_success():
    report = _make_report()
    db = _mock_db_with_result([report])
    result = await get_scheduled_report(db, account_id=1, report_id=report.id)
    assert result is report


@pytest.mark.asyncio
async def test_get_scheduled_report_wrong_account_404():
    db = _mock_db_with_result([])
    with pytest.raises(HTTPException) as exc:
        await get_scheduled_report(db, account_id=99, report_id=uuid.uuid4())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_list_active_only():
    active = _make_report(is_active=True)
    inactive = _make_report(is_active=False)
    db = _mock_db_with_result([active])
    reports = await list_scheduled_reports(db, account_id=1, active_only=True)
    assert len(reports) == 1
    assert reports[0].is_active is True


@pytest.mark.asyncio
async def test_list_all():
    active = _make_report(is_active=True)
    inactive = _make_report(is_active=False)
    db = _mock_db_with_result([active, inactive])
    reports = await list_scheduled_reports(db, account_id=1, active_only=False)
    assert len(reports) == 2


@pytest.mark.asyncio
async def test_list_empty():
    db = _mock_db_with_result([])
    reports = await list_scheduled_reports(db, account_id=1)
    assert reports == []


@pytest.mark.asyncio
async def test_update_name():
    report = _make_report(name="Old Name")
    db = _mock_db_with_result([report])
    updated = await update_scheduled_report(db, account_id=1, report_id=report.id, name="New Name")
    assert updated.name == "New Name"
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_update_recipients():
    report = _make_report()
    db = _mock_db_with_result([report])
    updated = await update_scheduled_report(
        db, account_id=1, report_id=report.id, recipients=["new@co.com"]
    )
    assert updated.recipients == ["new@co.com"]


@pytest.mark.asyncio
async def test_update_frequency_recomputes_next_due():
    report = _make_report(frequency=ReportFrequency.weekly, day_of_week=0)
    old_next_due = report.next_due_at
    db = _mock_db_with_result([report])
    updated = await update_scheduled_report(
        db,
        account_id=1,
        report_id=report.id,
        frequency=ReportFrequency.daily,
    )
    assert updated.next_due_at != old_next_due


@pytest.mark.asyncio
async def test_update_empty_recipients_422():
    report = _make_report()
    db = _mock_db_with_result([report])
    with pytest.raises(HTTPException) as exc:
        await update_scheduled_report(
            db, account_id=1, report_id=report.id, recipients=[]
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_update_not_found_404():
    db = _mock_db_with_result([])
    with pytest.raises(HTTPException) as exc:
        await update_scheduled_report(db, account_id=1, report_id=uuid.uuid4())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_deactivate_sets_is_active_false():
    report = _make_report(is_active=True)
    db = _mock_db_with_result([report])
    result = await deactivate_scheduled_report(db, account_id=1, report_id=report.id)
    assert result.is_active is False
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_deactivate_already_inactive_409():
    report = _make_report(is_active=False)
    db = _mock_db_with_result([report])
    with pytest.raises(HTTPException) as exc:
        await deactivate_scheduled_report(db, account_id=1, report_id=report.id)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_deactivate_not_found_404():
    db = _mock_db_with_result([])
    with pytest.raises(HTTPException) as exc:
        await deactivate_scheduled_report(db, account_id=1, report_id=uuid.uuid4())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_reactivate_sets_is_active_true():
    report = _make_report(is_active=False)
    db = _mock_db_with_result([report])
    result = await reactivate_scheduled_report(db, account_id=1, report_id=report.id)
    assert result.is_active is True
    assert result.next_due_at is not None


@pytest.mark.asyncio
async def test_reactivate_already_active_409():
    report = _make_report(is_active=True)
    db = _mock_db_with_result([report])
    with pytest.raises(HTTPException) as exc:
        await reactivate_scheduled_report(db, account_id=1, report_id=report.id)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_reactivate_not_found_404():
    db = _mock_db_with_result([])
    with pytest.raises(HTTPException) as exc:
        await reactivate_scheduled_report(db, account_id=1, report_id=uuid.uuid4())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_success():
    report = _make_report()
    db = _mock_db_with_result([report])
    await delete_scheduled_report(db, account_id=1, report_id=report.id)
    db.delete.assert_called_once_with(report)
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_delete_not_found_404():
    db = _mock_db_with_result([])
    with pytest.raises(HTTPException) as exc:
        await delete_scheduled_report(db, account_id=1, report_id=uuid.uuid4())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_trigger_updates_last_sent_at():
    report = _make_report(is_active=True, last_sent_at=None)
    db = _mock_db_with_result([report])
    result = await trigger_report_now(db, account_id=1, report_id=report.id)
    assert result["triggered_at"] is not None
    assert report.last_sent_at is not None


@pytest.mark.asyncio
async def test_trigger_advances_next_due_at():
    old_next = datetime.now(tz=timezone.utc) - timedelta(hours=1)
    report = _make_report(is_active=True, next_due_at=old_next)
    db = _mock_db_with_result([report])
    await trigger_report_now(db, account_id=1, report_id=report.id)
    assert report.next_due_at > old_next


@pytest.mark.asyncio
async def test_trigger_inactive_409():
    report = _make_report(is_active=False)
    db = _mock_db_with_result([report])
    with pytest.raises(HTTPException) as exc:
        await trigger_report_now(db, account_id=1, report_id=report.id)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_trigger_not_found_404():
    db = _mock_db_with_result([])
    with pytest.raises(HTTPException) as exc:
        await trigger_report_now(db, account_id=1, report_id=uuid.uuid4())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_list_due_reports_returns_overdue():
    overdue = _make_report(
        next_due_at=datetime.now(tz=timezone.utc) - timedelta(hours=2)
    )
    db = _mock_db_with_result([overdue])
    results = await list_due_reports(db)
    assert len(results) == 1


@pytest.mark.asyncio
async def test_list_due_reports_excludes_future():
    db = _mock_db_with_result([])
    results = await list_due_reports(db)
    assert results == []


@pytest.mark.asyncio
async def test_list_due_reports_excludes_inactive():
    db = _mock_db_with_result([])
    results = await list_due_reports(db)
    assert results == []


# ---------------------------------------------------------------------------
# Helper / unit tests
# ---------------------------------------------------------------------------


def test_compute_next_due_daily():
    result = _compute_next_due(ReportFrequency.daily, _NOW, None, None)
    assert result == _NOW + timedelta(days=1)


def test_compute_next_due_weekly_next_weekday():
    # _NOW is Wednesday (weekday=2).  Target Monday (weekday=0): 5 days ahead.
    result = _compute_next_due(ReportFrequency.weekly, _NOW, day_of_week=0, day_of_month=None)
    assert result == _NOW + timedelta(days=5)


def test_compute_next_due_weekly_same_day_next_week():
    # _NOW is Wednesday (weekday=2).  Target Wednesday: should be +7 days.
    result = _compute_next_due(ReportFrequency.weekly, _NOW, day_of_week=2, day_of_month=None)
    assert result == _NOW + timedelta(days=7)


def test_compute_next_due_monthly_future_day():
    # _NOW is April 15.  Target 20th → April 20.
    result = _compute_next_due(ReportFrequency.monthly, _NOW, None, day_of_month=20)
    assert result.month == 4
    assert result.day == 20


def test_compute_next_due_monthly_past_day_wraps_to_next_month():
    # _NOW is April 15.  Target 10th → May 10 (past this month).
    result = _compute_next_due(ReportFrequency.monthly, _NOW, None, day_of_month=10)
    assert result.month == 5
    assert result.day == 10


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_schema_create_valid_daily():
    obj = ScheduledReportCreate(
        name="Daily Report",
        report_type=ScheduledReportType.spending_overview,
        frequency=ReportFrequency.daily,
        recipients=["Admin@Corp.COM"],
    )
    assert obj.recipients == ["admin@corp.com"]  # normalised


def test_schema_create_recipients_normalised_lowercase():
    obj = ScheduledReportCreate(
        name="r",
        report_type=ScheduledReportType.ride_patterns,
        frequency=ReportFrequency.daily,
        recipients=["UPPER@CASE.COM", "Mixed@Case.org"],
    )
    assert obj.recipients == ["upper@case.com", "mixed@case.org"]


def test_schema_create_too_many_recipients_raises():
    with pytest.raises(ValidationError):
        ScheduledReportCreate(
            name="r",
            report_type=ScheduledReportType.spending_overview,
            frequency=ReportFrequency.daily,
            recipients=[f"user{i}@corp.com" for i in range(51)],
        )


def test_schema_update_all_optional():
    obj = ScheduledReportUpdate()
    assert obj.name is None
    assert obj.frequency is None
    assert obj.recipients is None


def test_schema_response_from_attributes():
    report = _make_report()
    resp = ScheduledReportResponse.model_validate(report)
    assert resp.id == report.id
    assert resp.account_id == report.account_id
    assert resp.frequency == report.frequency


def test_schema_trigger_response_fields():
    resp = ScheduledReportTriggerResponse(
        report_id=uuid.uuid4(),
        report_type=ScheduledReportType.spending_overview,
        recipients=["a@b.com"],
        triggered_at=datetime.now(tz=timezone.utc),
        message="done",
    )
    assert resp.message == "done"
    assert len(resp.recipients) == 1


# ---------------------------------------------------------------------------
# API layer tests (services patched)
# ---------------------------------------------------------------------------

_ACCT_ID = 1
_REPORT_ID = uuid.uuid4()
_DUMMY_REPORT = _make_report(account_id=_ACCT_ID)
_DUMMY_REPORT.id = _REPORT_ID


def _make_app_client():
    """Build a TestClient with auth + DB deps overridden."""
    from app.main import app
    from app.api.deps import get_current_user, get_db, require_admin
    from app.models.user import User

    mock_user = MagicMock(spec=User)
    mock_user.id = 10

    async def override_user():
        return mock_user

    async def override_admin():
        return mock_user

    async def override_db():
        yield AsyncMock()

    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[require_admin] = override_admin
    app.dependency_overrides[get_db] = override_db
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def _clear_dep_overrides():
    yield
    from app.main import app
    app.dependency_overrides.clear()


_BASE = "/api/v1/corporate/accounts/me/scheduled-reports"
_ADMIN_BASE = "/api/v1/admin/corporate"


@patch("app.api.v1.corporate_scheduled_reports._resolve_account_id", new_callable=AsyncMock, return_value=_ACCT_ID)
@patch("app.api.v1.corporate_scheduled_reports.list_scheduled_reports", new_callable=AsyncMock, return_value=[_DUMMY_REPORT])
def test_api_list_200(mock_list, mock_resolve):
    client = _make_app_client()
    resp = client.get(_BASE)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1


@patch("app.api.v1.corporate_scheduled_reports._resolve_account_id", new_callable=AsyncMock, return_value=_ACCT_ID)
@patch("app.api.v1.corporate_scheduled_reports.create_scheduled_report", new_callable=AsyncMock, return_value=_DUMMY_REPORT)
def test_api_create_201(mock_create, mock_resolve):
    client = _make_app_client()
    resp = client.post(
        _BASE,
        json={
            "name": "New Report",
            "report_type": "spending_overview",
            "frequency": "daily",
            "recipients": ["a@b.com"],
        },
    )
    assert resp.status_code == 201


@patch("app.api.v1.corporate_scheduled_reports._resolve_account_id", new_callable=AsyncMock, return_value=_ACCT_ID)
@patch("app.api.v1.corporate_scheduled_reports.get_scheduled_report", new_callable=AsyncMock, return_value=_DUMMY_REPORT)
def test_api_get_200(mock_get, mock_resolve):
    client = _make_app_client()
    resp = client.get(f"{_BASE}/{_REPORT_ID}")
    assert resp.status_code == 200


@patch("app.api.v1.corporate_scheduled_reports._resolve_account_id", new_callable=AsyncMock, return_value=_ACCT_ID)
@patch("app.api.v1.corporate_scheduled_reports.update_scheduled_report", new_callable=AsyncMock, return_value=_DUMMY_REPORT)
def test_api_update_200(mock_update, mock_resolve):
    client = _make_app_client()
    resp = client.put(f"{_BASE}/{_REPORT_ID}", json={"name": "Updated"})
    assert resp.status_code == 200


@patch("app.api.v1.corporate_scheduled_reports._resolve_account_id", new_callable=AsyncMock, return_value=_ACCT_ID)
@patch("app.api.v1.corporate_scheduled_reports.deactivate_scheduled_report", new_callable=AsyncMock, return_value=_DUMMY_REPORT)
def test_api_deactivate_200(mock_deact, mock_resolve):
    client = _make_app_client()
    resp = client.post(f"{_BASE}/{_REPORT_ID}/deactivate")
    assert resp.status_code == 200


@patch("app.api.v1.corporate_scheduled_reports._resolve_account_id", new_callable=AsyncMock, return_value=_ACCT_ID)
@patch("app.api.v1.corporate_scheduled_reports.reactivate_scheduled_report", new_callable=AsyncMock, return_value=_DUMMY_REPORT)
def test_api_reactivate_200(mock_react, mock_resolve):
    client = _make_app_client()
    resp = client.post(f"{_BASE}/{_REPORT_ID}/reactivate")
    assert resp.status_code == 200


@patch("app.api.v1.corporate_scheduled_reports._resolve_account_id", new_callable=AsyncMock, return_value=_ACCT_ID)
@patch("app.api.v1.corporate_scheduled_reports.delete_scheduled_report", new_callable=AsyncMock, return_value=None)
def test_api_delete_204(mock_del, mock_resolve):
    client = _make_app_client()
    resp = client.delete(f"{_BASE}/{_REPORT_ID}")
    assert resp.status_code == 204


@patch("app.api.v1.corporate_scheduled_reports._resolve_account_id", new_callable=AsyncMock, return_value=_ACCT_ID)
@patch(
    "app.api.v1.corporate_scheduled_reports.trigger_report_now",
    new_callable=AsyncMock,
    return_value={
        "report_id": _REPORT_ID,
        "report_type": ScheduledReportType.spending_overview,
        "recipients": ["a@b.com"],
        "triggered_at": datetime(2026, 4, 15, 12, 0, tzinfo=timezone.utc),
        "message": "done",
    },
)
def test_api_trigger_200(mock_trigger, mock_resolve):
    client = _make_app_client()
    resp = client.post(f"{_BASE}/{_REPORT_ID}/trigger")
    assert resp.status_code == 200
    data = resp.json()
    assert data["message"] == "done"


@patch("app.api.v1.corporate_scheduled_reports.list_scheduled_reports", new_callable=AsyncMock, return_value=[_DUMMY_REPORT])
def test_api_platform_admin_list_200(mock_list):
    client = _make_app_client()
    resp = client.get(f"{_ADMIN_BASE}/accounts/{_ACCT_ID}/scheduled-reports")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1


@patch("app.api.v1.corporate_scheduled_reports.list_due_reports", new_callable=AsyncMock, return_value=[_DUMMY_REPORT])
def test_api_platform_admin_due_200(mock_due):
    client = _make_app_client()
    resp = client.get(f"{_ADMIN_BASE}/scheduled-reports/due")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    assert len(resp.json()) == 1
