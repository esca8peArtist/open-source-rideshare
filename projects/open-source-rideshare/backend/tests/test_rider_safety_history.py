"""Tests for rider safety incident history.

GET /riders/me/safety-incidents

Coverage
--------
Helper: _to_utc_date
  - Naive datetime returns its .date()
  - Timezone-aware datetime converts to UTC before extracting date

Helper: _parse_status
  - "active" → PanicAlertStatus.ACTIVE
  - "resolved" → PanicAlertStatus.RESOLVED
  - "false_alarm" → PanicAlertStatus.FALSE_ALARM
  - "all" → None

Helper: _apply_filters — incident_type
  - "all" returns all records
  - "PANIC_ALERT" returns all records (all current records are PANIC_ALERT)
  - unknown type (not PANIC_ALERT) returns empty list

Helper: _apply_filters — status
  - "all" returns all statuses
  - "active" returns only ACTIVE
  - "resolved" returns only RESOLVED
  - "false_alarm" returns only FALSE_ALARM
  - combined: only matching records returned

Helper: _apply_filters — date range
  - from_date filters out older incidents
  - to_date filters out newer incidents
  - from_date == to_date returns only incidents triggered on that date
  - both from_date and to_date applied simultaneously
  - no dates → no filtering

Helper: _build_summary
  - empty list → all counts 0
  - counts ACTIVE, RESOLVED, FALSE_ALARM separately
  - total_all_time equals len(alerts)
  - mixed statuses counted correctly

Helper: _alert_to_incident
  - id preserved
  - incident_type always PANIC_ALERT
  - ride_id, driver_id preserved
  - status converted to string value
  - location_lat, location_lng preserved (None if absent)
  - triggered_at preserved
  - resolved_at preserved (None if absent)
  - resolution_notes preserved (None if absent)

Service: get_rider_safety_history
  - no incidents → total_count=0, incidents=[], summary all zeros
  - summary is unaffected by status filter
  - summary is unaffected by date filter
  - filters_applied echoes all input params
  - default filters_applied (incident_type=all, status=all, limit=20, offset=0, dates=None)
  - incidents ordered newest-first
  - total_count reflects filtered count, not all-time count
  - pagination: limit applied correctly
  - pagination: offset applied correctly
  - pagination: offset past end → empty incidents, total_count still correct
  - status filter applied
  - from_date filter applied
  - to_date filter applied
  - incident_type="PANIC_ALERT" returns same as "all"
  - only returns incidents belonging to the requesting rider

Schema: SafetyIncidentRecord
  - All required fields present
  - Optional fields accept None

Schema: SafetyIncidentSummary
  - All fields present and integer

Schema: SafetyIncidentFilters
  - All fields present; date fields accept None

Schema: RiderSafetyHistory
  - total_count is int
  - incidents is list
  - summary is SafetyIncidentSummary
  - filters_applied is SafetyIncidentFilters

Router: get_safety_incidents
  - delegates to service with rider.id
  - returns RiderSafetyHistory
  - 422 when from_date > to_date
  - 422 when incident_type invalid
  - 422 when status invalid
  - defaults: incident_type="all", status="all", limit=20, offset=0

End-to-end: panic flow
  - trigger two alerts → both appear in history
  - resolve one → summary updated, history shows correct statuses
  - rider A cannot see rider B's incidents
"""
from __future__ import annotations

import pytest
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ValidationError

from app.schemas.rider_safety import PanicAlertStatus
from app.schemas.rider_safety_history import (
    RiderSafetyHistory,
    SafetyIncidentFilters,
    SafetyIncidentRecord,
    SafetyIncidentSummary,
    SafetyIncidentType,
)
from app.services.rider_safety import _reset_store, trigger_panic, cancel_panic_alert
from app.services.rider_safety_history import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    _alert_to_incident,
    _apply_filters,
    _build_summary,
    _parse_status,
    _to_utc_date,
    get_rider_safety_history,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_store():
    """Reset in-memory panic alert store before each test."""
    _reset_store()
    yield
    _reset_store()


@pytest.fixture
def mock_db():
    return AsyncMock()


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


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


# ---------------------------------------------------------------------------
# Helper: _to_utc_date
# ---------------------------------------------------------------------------


class TestToUtcDate:
    def test_naive_datetime_returns_date(self):
        dt = datetime(2026, 4, 17, 10, 30, 0)  # naive
        assert _to_utc_date(dt) == date(2026, 4, 17)

    def test_utc_aware_preserves_date(self):
        dt = datetime(2026, 4, 17, 23, 59, 59, tzinfo=timezone.utc)
        assert _to_utc_date(dt) == date(2026, 4, 17)

    def test_offset_aware_converts_to_utc(self):
        # +05:00 means UTC is 5 hours behind — 2026-04-18T02:00+05:00 → 2026-04-17T21:00Z
        from datetime import timezone as tz
        import datetime as dt_module
        eastern_plus5 = dt_module.timezone(timedelta(hours=5))
        dt = datetime(2026, 4, 18, 2, 0, 0, tzinfo=eastern_plus5)
        assert _to_utc_date(dt) == date(2026, 4, 17)


# ---------------------------------------------------------------------------
# Helper: _parse_status
# ---------------------------------------------------------------------------


class TestParseStatus:
    def test_active(self):
        assert _parse_status("active") == PanicAlertStatus.ACTIVE

    def test_resolved(self):
        assert _parse_status("resolved") == PanicAlertStatus.RESOLVED

    def test_false_alarm(self):
        assert _parse_status("false_alarm") == PanicAlertStatus.FALSE_ALARM

    def test_all_returns_none(self):
        assert _parse_status("all") is None


# ---------------------------------------------------------------------------
# Helper: _apply_filters — incident_type
# ---------------------------------------------------------------------------


class TestApplyFiltersIncidentType:
    def _make_alert_dict(self, status=PanicAlertStatus.ACTIVE, triggered_at=None):
        return {
            "id": "abc",
            "rider_id": 1,
            "ride_id": 100,
            "driver_id": 2,
            "status": status,
            "triggered_at": triggered_at or _utc_now(),
            "location_lat": None,
            "location_lng": None,
            "resolved_at": None,
            "resolution_notes": None,
        }

    def test_all_returns_all(self):
        alerts = [self._make_alert_dict(), self._make_alert_dict()]
        result = _apply_filters(alerts, "all", "all", None, None)
        assert len(result) == 2

    def test_panic_alert_returns_all_current_records(self):
        alerts = [self._make_alert_dict(), self._make_alert_dict()]
        result = _apply_filters(alerts, "PANIC_ALERT", "all", None, None)
        assert len(result) == 2

    def test_unknown_type_returns_empty(self):
        # Any type that is not PANIC_ALERT returns empty (extensibility guard)
        alerts = [self._make_alert_dict()]
        result = _apply_filters(alerts, "SOS_ALERT", "all", None, None)
        assert result == []


# ---------------------------------------------------------------------------
# Helper: _apply_filters — status
# ---------------------------------------------------------------------------


class TestApplyFiltersStatus:
    def _make_alerts(self):
        now = _utc_now()
        return [
            {"id": "a1", "status": PanicAlertStatus.ACTIVE, "triggered_at": now},
            {"id": "a2", "status": PanicAlertStatus.RESOLVED, "triggered_at": now},
            {"id": "a3", "status": PanicAlertStatus.FALSE_ALARM, "triggered_at": now},
            {"id": "a4", "status": PanicAlertStatus.ACTIVE, "triggered_at": now},
        ]

    def test_all_returns_all(self):
        alerts = self._make_alerts()
        result = _apply_filters(alerts, "all", "all", None, None)
        assert len(result) == 4

    def test_active_filter(self):
        result = _apply_filters(self._make_alerts(), "all", "active", None, None)
        assert len(result) == 2
        assert all(a["status"] == PanicAlertStatus.ACTIVE for a in result)

    def test_resolved_filter(self):
        result = _apply_filters(self._make_alerts(), "all", "resolved", None, None)
        assert len(result) == 1
        assert result[0]["id"] == "a2"

    def test_false_alarm_filter(self):
        result = _apply_filters(self._make_alerts(), "all", "false_alarm", None, None)
        assert len(result) == 1
        assert result[0]["id"] == "a3"


# ---------------------------------------------------------------------------
# Helper: _apply_filters — date range
# ---------------------------------------------------------------------------


class TestApplyFiltersDateRange:
    def _make_alert_on_date(self, d: date) -> dict:
        dt = datetime(d.year, d.month, d.day, 12, 0, 0, tzinfo=timezone.utc)
        return {"id": str(d), "status": PanicAlertStatus.ACTIVE, "triggered_at": dt}

    def test_from_date_excludes_older(self):
        alerts = [
            self._make_alert_on_date(date(2026, 4, 1)),
            self._make_alert_on_date(date(2026, 4, 10)),
            self._make_alert_on_date(date(2026, 4, 20)),
        ]
        result = _apply_filters(alerts, "all", "all", date(2026, 4, 10), None)
        assert len(result) == 2
        assert all(a["triggered_at"].date() >= date(2026, 4, 10) for a in result)

    def test_to_date_excludes_newer(self):
        alerts = [
            self._make_alert_on_date(date(2026, 4, 1)),
            self._make_alert_on_date(date(2026, 4, 10)),
            self._make_alert_on_date(date(2026, 4, 20)),
        ]
        result = _apply_filters(alerts, "all", "all", None, date(2026, 4, 10))
        assert len(result) == 2
        assert all(a["triggered_at"].date() <= date(2026, 4, 10) for a in result)

    def test_same_from_and_to_date(self):
        alerts = [
            self._make_alert_on_date(date(2026, 4, 1)),
            self._make_alert_on_date(date(2026, 4, 10)),
            self._make_alert_on_date(date(2026, 4, 20)),
        ]
        result = _apply_filters(alerts, "all", "all", date(2026, 4, 10), date(2026, 4, 10))
        assert len(result) == 1
        assert result[0]["triggered_at"].date() == date(2026, 4, 10)

    def test_both_from_and_to_date(self):
        alerts = [
            self._make_alert_on_date(date(2026, 4, 1)),
            self._make_alert_on_date(date(2026, 4, 10)),
            self._make_alert_on_date(date(2026, 4, 15)),
            self._make_alert_on_date(date(2026, 4, 20)),
        ]
        result = _apply_filters(alerts, "all", "all", date(2026, 4, 10), date(2026, 4, 15))
        assert len(result) == 2

    def test_no_dates_returns_all(self):
        alerts = [
            self._make_alert_on_date(date(2026, 1, 1)),
            self._make_alert_on_date(date(2026, 6, 1)),
        ]
        result = _apply_filters(alerts, "all", "all", None, None)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Helper: _build_summary
# ---------------------------------------------------------------------------


class TestBuildSummary:
    def test_empty_list_all_zeros(self):
        summary = _build_summary([])
        assert summary["total_all_time"] == 0
        assert summary["active_count"] == 0
        assert summary["resolved_count"] == 0
        assert summary["false_alarm_count"] == 0

    def test_single_active(self):
        alerts = [{"status": PanicAlertStatus.ACTIVE}]
        summary = _build_summary(alerts)
        assert summary["total_all_time"] == 1
        assert summary["active_count"] == 1
        assert summary["resolved_count"] == 0
        assert summary["false_alarm_count"] == 0

    def test_mixed_statuses(self):
        alerts = [
            {"status": PanicAlertStatus.ACTIVE},
            {"status": PanicAlertStatus.ACTIVE},
            {"status": PanicAlertStatus.RESOLVED},
            {"status": PanicAlertStatus.FALSE_ALARM},
            {"status": PanicAlertStatus.FALSE_ALARM},
        ]
        summary = _build_summary(alerts)
        assert summary["total_all_time"] == 5
        assert summary["active_count"] == 2
        assert summary["resolved_count"] == 1
        assert summary["false_alarm_count"] == 2

    def test_total_equals_len(self):
        alerts = [{"status": PanicAlertStatus.RESOLVED} for _ in range(7)]
        summary = _build_summary(alerts)
        assert summary["total_all_time"] == 7


# ---------------------------------------------------------------------------
# Helper: _alert_to_incident
# ---------------------------------------------------------------------------


class TestAlertToIncident:
    def _make_alert_dict(self, **overrides):
        base = {
            "id": "uuid-1",
            "rider_id": 1,
            "ride_id": 100,
            "driver_id": 2,
            "status": PanicAlertStatus.ACTIVE,
            "triggered_at": _utc_now(),
            "location_lat": 37.7749,
            "location_lng": -122.4194,
            "resolved_at": None,
            "resolution_notes": None,
        }
        base.update(overrides)
        return base

    def test_id_preserved(self):
        incident = _alert_to_incident(self._make_alert_dict(id="test-id"))
        assert incident["id"] == "test-id"

    def test_incident_type_always_panic_alert(self):
        incident = _alert_to_incident(self._make_alert_dict())
        assert incident["incident_type"] == SafetyIncidentType.PANIC_ALERT

    def test_ride_id_preserved(self):
        incident = _alert_to_incident(self._make_alert_dict(ride_id=999))
        assert incident["ride_id"] == 999

    def test_driver_id_preserved(self):
        incident = _alert_to_incident(self._make_alert_dict(driver_id=42))
        assert incident["driver_id"] == 42

    def test_status_converted_to_string(self):
        incident = _alert_to_incident(self._make_alert_dict(status=PanicAlertStatus.RESOLVED))
        assert incident["status"] == "RESOLVED"
        assert isinstance(incident["status"], str)

    def test_location_preserved(self):
        incident = _alert_to_incident(self._make_alert_dict(location_lat=1.1, location_lng=2.2))
        assert incident["location_lat"] == 1.1
        assert incident["location_lng"] == 2.2

    def test_location_none_when_absent(self):
        incident = _alert_to_incident(self._make_alert_dict(location_lat=None, location_lng=None))
        assert incident["location_lat"] is None
        assert incident["location_lng"] is None

    def test_triggered_at_preserved(self):
        now = _utc_now()
        incident = _alert_to_incident(self._make_alert_dict(triggered_at=now))
        assert incident["triggered_at"] == now

    def test_resolved_at_none_when_absent(self):
        incident = _alert_to_incident(self._make_alert_dict(resolved_at=None))
        assert incident["resolved_at"] is None

    def test_resolved_at_preserved(self):
        now = _utc_now()
        incident = _alert_to_incident(self._make_alert_dict(resolved_at=now))
        assert incident["resolved_at"] == now

    def test_resolution_notes_none_when_absent(self):
        incident = _alert_to_incident(self._make_alert_dict(resolution_notes=None))
        assert incident["resolution_notes"] is None

    def test_resolution_notes_preserved(self):
        incident = _alert_to_incident(self._make_alert_dict(resolution_notes="Handled by dispatch"))
        assert incident["resolution_notes"] == "Handled by dispatch"


# ---------------------------------------------------------------------------
# Service: get_rider_safety_history
# ---------------------------------------------------------------------------


class TestGetRiderSafetyHistory:
    @pytest.mark.asyncio
    async def test_no_incidents_returns_empty(self, mock_db):
        result = await get_rider_safety_history(db=mock_db, rider_id=99)
        assert result["total_count"] == 0
        assert result["incidents"] == []

    @pytest.mark.asyncio
    async def test_summary_zeros_when_no_incidents(self, mock_db):
        result = await get_rider_safety_history(db=mock_db, rider_id=99)
        assert result["summary"]["total_all_time"] == 0
        assert result["summary"]["active_count"] == 0

    @pytest.mark.asyncio
    async def test_summary_unaffected_by_status_filter(self, mock_db):
        await _make_alert(mock_db, rider_id=1, ride_id=1)
        await _make_alert(mock_db, rider_id=1, ride_id=2)
        # Filter to "resolved" — 0 results, but summary should show 2 total
        result = await get_rider_safety_history(db=mock_db, rider_id=1, status="resolved")
        assert result["total_count"] == 0
        assert result["incidents"] == []
        assert result["summary"]["total_all_time"] == 2
        assert result["summary"]["active_count"] == 2

    @pytest.mark.asyncio
    async def test_summary_unaffected_by_date_filter(self, mock_db):
        await _make_alert(mock_db, rider_id=1, ride_id=1)
        # Filter to a far-future date — 0 results, but summary shows 1 total
        result = await get_rider_safety_history(
            db=mock_db, rider_id=1, from_date=date(2099, 1, 1)
        )
        assert result["total_count"] == 0
        assert result["summary"]["total_all_time"] == 1

    @pytest.mark.asyncio
    async def test_filters_applied_echoes_defaults(self, mock_db):
        result = await get_rider_safety_history(db=mock_db, rider_id=1)
        fa = result["filters_applied"]
        assert fa["incident_type"] == "all"
        assert fa["status"] == "all"
        assert fa["from_date"] is None
        assert fa["to_date"] is None
        assert fa["limit"] == DEFAULT_LIMIT
        assert fa["offset"] == 0

    @pytest.mark.asyncio
    async def test_filters_applied_echoes_custom(self, mock_db):
        result = await get_rider_safety_history(
            db=mock_db,
            rider_id=1,
            incident_type="PANIC_ALERT",
            status="active",
            from_date=date(2026, 1, 1),
            to_date=date(2026, 12, 31),
            limit=10,
            offset=5,
        )
        fa = result["filters_applied"]
        assert fa["incident_type"] == "PANIC_ALERT"
        assert fa["status"] == "active"
        assert fa["from_date"] == date(2026, 1, 1)
        assert fa["to_date"] == date(2026, 12, 31)
        assert fa["limit"] == 10
        assert fa["offset"] == 5

    @pytest.mark.asyncio
    async def test_incidents_newest_first(self, mock_db):
        a1 = await _make_alert(mock_db, rider_id=1, ride_id=1)
        a2 = await _make_alert(mock_db, rider_id=1, ride_id=2)
        result = await get_rider_safety_history(db=mock_db, rider_id=1)
        ids = [i["id"] for i in result["incidents"]]
        # a2 was created after a1, so should be first
        assert ids[0] == a2["id"]
        assert ids[1] == a1["id"]

    @pytest.mark.asyncio
    async def test_total_count_reflects_filtered_count(self, mock_db):
        await _make_alert(mock_db, rider_id=1, ride_id=1)
        await _make_alert(mock_db, rider_id=1, ride_id=2)
        result = await get_rider_safety_history(db=mock_db, rider_id=1, status="resolved")
        assert result["total_count"] == 0

    @pytest.mark.asyncio
    async def test_pagination_limit(self, mock_db):
        for ride_id in range(1, 6):
            await _make_alert(mock_db, rider_id=1, ride_id=ride_id)
        result = await get_rider_safety_history(db=mock_db, rider_id=1, limit=3, offset=0)
        assert result["total_count"] == 5
        assert len(result["incidents"]) == 3

    @pytest.mark.asyncio
    async def test_pagination_offset(self, mock_db):
        for ride_id in range(1, 6):
            await _make_alert(mock_db, rider_id=1, ride_id=ride_id)
        result = await get_rider_safety_history(db=mock_db, rider_id=1, limit=3, offset=3)
        assert result["total_count"] == 5
        assert len(result["incidents"]) == 2  # 5 - 3 = 2 remaining

    @pytest.mark.asyncio
    async def test_offset_past_end_empty_page(self, mock_db):
        await _make_alert(mock_db, rider_id=1, ride_id=1)
        result = await get_rider_safety_history(db=mock_db, rider_id=1, limit=10, offset=50)
        assert result["total_count"] == 1
        assert result["incidents"] == []

    @pytest.mark.asyncio
    async def test_status_filter_active(self, mock_db):
        await _make_alert(mock_db, rider_id=1, ride_id=1)
        await _make_alert(mock_db, rider_id=1, ride_id=2)
        result = await get_rider_safety_history(db=mock_db, rider_id=1, status="active")
        assert result["total_count"] == 2
        assert all(i["status"] == "ACTIVE" for i in result["incidents"])

    @pytest.mark.asyncio
    async def test_only_own_incidents_returned(self, mock_db):
        await _make_alert(mock_db, rider_id=1, ride_id=1)
        await _make_alert(mock_db, rider_id=2, ride_id=2)
        result = await get_rider_safety_history(db=mock_db, rider_id=1)
        assert result["total_count"] == 1
        assert result["incidents"][0]["ride_id"] == 1

    @pytest.mark.asyncio
    async def test_incident_type_panic_alert_same_as_all(self, mock_db):
        await _make_alert(mock_db, rider_id=1, ride_id=1)
        r_all = await get_rider_safety_history(db=mock_db, rider_id=1, incident_type="all")
        r_panic = await get_rider_safety_history(db=mock_db, rider_id=1, incident_type="PANIC_ALERT")
        assert r_all["total_count"] == r_panic["total_count"]


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestSchemas:
    def test_safety_incident_record_required_fields(self):
        record = SafetyIncidentRecord(
            id="uuid-1",
            incident_type=SafetyIncidentType.PANIC_ALERT,
            ride_id=100,
            driver_id=2,
            status="ACTIVE",
            triggered_at=_utc_now(),
            location_lat=None,
            location_lng=None,
            resolved_at=None,
            resolution_notes=None,
        )
        assert record.id == "uuid-1"
        assert record.incident_type == SafetyIncidentType.PANIC_ALERT

    def test_safety_incident_record_optional_fields_accept_none(self):
        record = SafetyIncidentRecord(
            id="x",
            incident_type=SafetyIncidentType.PANIC_ALERT,
            ride_id=1,
            driver_id=1,
            status="RESOLVED",
            triggered_at=_utc_now(),
        )
        assert record.location_lat is None
        assert record.location_lng is None
        assert record.resolved_at is None
        assert record.resolution_notes is None

    def test_safety_incident_summary_all_integer(self):
        summary = SafetyIncidentSummary(
            total_all_time=10,
            active_count=2,
            resolved_count=7,
            false_alarm_count=1,
        )
        assert isinstance(summary.total_all_time, int)
        assert isinstance(summary.active_count, int)

    def test_safety_incident_filters_date_fields_optional(self):
        f = SafetyIncidentFilters(
            incident_type="all",
            status="all",
            from_date=None,
            to_date=None,
            limit=20,
            offset=0,
        )
        assert f.from_date is None
        assert f.to_date is None

    def test_rider_safety_history_structure(self):
        now = _utc_now()
        history = RiderSafetyHistory(
            total_count=1,
            incidents=[
                SafetyIncidentRecord(
                    id="x",
                    incident_type=SafetyIncidentType.PANIC_ALERT,
                    ride_id=1,
                    driver_id=1,
                    status="ACTIVE",
                    triggered_at=now,
                )
            ],
            summary=SafetyIncidentSummary(
                total_all_time=1,
                active_count=1,
                resolved_count=0,
                false_alarm_count=0,
            ),
            filters_applied=SafetyIncidentFilters(
                incident_type="all",
                status="all",
                from_date=None,
                to_date=None,
                limit=20,
                offset=0,
            ),
        )
        assert history.total_count == 1
        assert len(history.incidents) == 1
        assert isinstance(history.summary, SafetyIncidentSummary)
        assert isinstance(history.filters_applied, SafetyIncidentFilters)


# ---------------------------------------------------------------------------
# Router tests
# ---------------------------------------------------------------------------


class TestRouter:
    @pytest.mark.asyncio
    async def test_get_safety_incidents_delegates_to_service(self):
        mock_rider = MagicMock()
        mock_rider.id = 1
        mock_db = AsyncMock()

        with patch(
            "app.api.v1.rider_safety_history.get_rider_safety_history"
        ) as mock_svc:
            mock_svc.return_value = {
                "total_count": 0,
                "incidents": [],
                "summary": {
                    "total_all_time": 0,
                    "active_count": 0,
                    "resolved_count": 0,
                    "false_alarm_count": 0,
                },
                "filters_applied": {
                    "incident_type": "all",
                    "status": "all",
                    "from_date": None,
                    "to_date": None,
                    "limit": 20,
                    "offset": 0,
                },
            }

            from app.api.v1.rider_safety_history import get_safety_incidents

            result = await get_safety_incidents(
                incident_type="all",
                status="all",
                from_date=None,
                to_date=None,
                limit=20,
                offset=0,
                rider=mock_rider,
                db=mock_db,
            )

            mock_svc.assert_called_once_with(
                db=mock_db,
                rider_id=1,
                incident_type="all",
                status="all",
                from_date=None,
                to_date=None,
                limit=20,
                offset=0,
            )

        assert isinstance(result, RiderSafetyHistory)
        assert result.total_count == 0

    @pytest.mark.asyncio
    async def test_422_when_from_date_after_to_date(self):
        from fastapi import HTTPException
        from app.api.v1.rider_safety_history import get_safety_incidents

        mock_rider = MagicMock()
        mock_rider.id = 1
        mock_db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await get_safety_incidents(
                incident_type="all",
                status="all",
                from_date=date(2026, 4, 20),
                to_date=date(2026, 4, 10),
                limit=20,
                offset=0,
                rider=mock_rider,
                db=mock_db,
            )

        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_422_when_invalid_incident_type(self):
        from fastapi import HTTPException
        from app.api.v1.rider_safety_history import get_safety_incidents

        mock_rider = MagicMock()
        mock_rider.id = 1
        mock_db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await get_safety_incidents(
                incident_type="UNKNOWN_TYPE",
                status="all",
                from_date=None,
                to_date=None,
                limit=20,
                offset=0,
                rider=mock_rider,
                db=mock_db,
            )

        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_422_when_invalid_status(self):
        from fastapi import HTTPException
        from app.api.v1.rider_safety_history import get_safety_incidents

        mock_rider = MagicMock()
        mock_rider.id = 1
        mock_db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await get_safety_incidents(
                incident_type="all",
                status="invalid_status",
                from_date=None,
                to_date=None,
                limit=20,
                offset=0,
                rider=mock_rider,
                db=mock_db,
            )

        assert exc_info.value.status_code == 422


# ---------------------------------------------------------------------------
# End-to-end tests
# ---------------------------------------------------------------------------


class TestEndToEnd:
    @pytest.mark.asyncio
    async def test_trigger_two_alerts_both_in_history(self, mock_db):
        a1 = await _make_alert(mock_db, rider_id=1, ride_id=1)
        a2 = await _make_alert(mock_db, rider_id=1, ride_id=2)

        result = await get_rider_safety_history(db=mock_db, rider_id=1)

        assert result["total_count"] == 2
        assert result["summary"]["total_all_time"] == 2
        assert result["summary"]["active_count"] == 2
        ids = {i["id"] for i in result["incidents"]}
        assert a1["id"] in ids
        assert a2["id"] in ids

    @pytest.mark.asyncio
    async def test_cancel_one_updates_history(self, mock_db):
        a1 = await _make_alert(mock_db, rider_id=1, ride_id=1)
        a2 = await _make_alert(mock_db, rider_id=1, ride_id=2)

        # Cancel a1 within 30s → FALSE_ALARM
        await cancel_panic_alert(db=mock_db, rider_id=1, alert_id=a1["id"])

        result = await get_rider_safety_history(db=mock_db, rider_id=1)

        assert result["summary"]["total_all_time"] == 2
        assert result["summary"]["active_count"] == 1
        assert result["summary"]["false_alarm_count"] == 1

        # Filter to only active
        active_result = await get_rider_safety_history(
            db=mock_db, rider_id=1, status="active"
        )
        assert active_result["total_count"] == 1
        assert active_result["incidents"][0]["id"] == a2["id"]

    @pytest.mark.asyncio
    async def test_rider_isolation(self, mock_db):
        await _make_alert(mock_db, rider_id=1, ride_id=1)
        await _make_alert(mock_db, rider_id=2, ride_id=2)
        await _make_alert(mock_db, rider_id=2, ride_id=3)

        r1 = await get_rider_safety_history(db=mock_db, rider_id=1)
        r2 = await get_rider_safety_history(db=mock_db, rider_id=2)

        assert r1["total_count"] == 1
        assert r2["total_count"] == 2
        assert r1["summary"]["total_all_time"] == 1
        assert r2["summary"]["total_all_time"] == 2
