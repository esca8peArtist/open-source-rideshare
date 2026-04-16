"""Tests for the Corporate Event Management feature.

Service layer (async, mocked DB):
  1.  create_event — creates with draft status
  2.  create_event — sets organizer_id and created_by_id to member_id
  3.  get_event — 404 when not found
  4.  get_event — returns event when found
  5.  list_events — returns paginated list
  6.  list_events — filters by status
  7.  update_event — 404 when not found
  8.  update_event — 409 when cancelled
  9.  update_event — 409 when completed
  10. update_event — partial update only writes supplied fields
  11. activate_event — 409 when not draft
  12. activate_event — success sets status to active
  13. cancel_event — 404 when not found
  14. cancel_event — 409 when completed
  15. cancel_event — 409 when already cancelled
  16. cancel_event — success sets status to cancelled
  17. complete_event — 409 when not active
  18. complete_event — success sets status to completed
  19. invite_attendees — 404 when event not found
  20. invite_attendees — 409 when event cancelled
  21. invite_attendees — skips duplicate member silently
  22. invite_attendees — inserts new attendees with invited status
  23. update_attendee_status — 404 when event not found
  24. update_attendee_status — 404 when attendee not found
  25. update_attendee_status — success updates status
  26. get_event_summary — 404 when not found
  27. get_event_summary — returns correct counts

Schema validation:
  28. EventCreate — title and event_location_name required
  29. EventCreate — optional fields default correctly
  30. EventUpdate — all fields optional
  31. InviteAttendeesRequest — member_ids min length 1
  32. InviteAttendeesRequest — member_ids max length 50
  33. EventResponse — from_attributes construction
  34. AttendeeResponse — from_attributes construction
  35. EventSummaryResponse — construction

API layer (service functions patched):
  36. POST create — 201 member can create
  37. POST create — 404 when no corporate account
  38. GET list — 200 member can list
  39. GET get — 200 member can view
  40. GET get — 404 not found
  41. PUT update — 200 member can update
  42. PUT update — 409 when cancelled or completed
  43. GET summary — 200 member can view summary
  44. POST activate — 403 non-admin cannot activate
  45. POST activate — 200 admin can activate
  46. POST cancel — 200 admin can cancel
  47. POST cancel — 403 non-admin cannot cancel
  48. POST complete — 200 admin can complete
  49. POST invite — 200 admin can invite attendees
  50. POST invite — 403 non-admin cannot invite
  51. PATCH attendee status — 200 admin can update
  52. GET platform list — 200 platform-admin list
  53. GET platform account list — 200 platform-admin account-specific list
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.corporate_event import CorporateEvent, CorporateEventAttendee
from app.schemas.corporate_event import (
    AttendeeListResponse,
    AttendeeResponse,
    AttendeeStatusUpdate,
    EventCreate,
    EventListResponse,
    EventResponse,
    EventSummaryResponse,
    EventUpdate,
    InviteAttendeesRequest,
)
from app.services.corporate_event import (
    activate_event,
    cancel_event,
    complete_event,
    create_event,
    get_event,
    get_event_summary,
    invite_attendees,
    list_all_events_platform,
    list_events,
    update_attendee_status,
    update_event,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACCOUNT_ID = 10
MEMBER_ID = 3
ADMIN_ID = 2
USER_ID = 1
EVENT_ID = 42
RIDE_ID = 99

_SERVICE = "app.services.corporate_event"
_ROUTER = "app.api.v1.corporate_events"

_NOW = datetime(2026, 4, 16, 9, 0, 0, tzinfo=timezone.utc)
_EVENT_DT = datetime(2026, 6, 15, 18, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    event_id: int = EVENT_ID,
    account_id: int = ACCOUNT_ID,
    organizer_id: int | None = MEMBER_ID,
    created_by_id: int | None = MEMBER_ID,
    title: str = "Q3 Team Offsite",
    description: str | None = None,
    event_location_name: str = "Grand Hyatt NYC",
    status: str = "draft",
    budget_usd=None,
    max_attendees: int | None = None,
    auto_approve_rides: bool = False,
    is_active: bool = True,
) -> CorporateEvent:
    """Build a minimal CorporateEvent instance for testing."""
    e = CorporateEvent()
    e.id = event_id
    e.account_id = account_id
    e.organizer_id = organizer_id
    e.created_by_id = created_by_id
    e.title = title
    e.description = description
    e.event_location_name = event_location_name
    e.event_address_line1 = None
    e.event_city = None
    e.event_state = None
    e.event_country = "US"
    e.event_latitude = None
    e.event_longitude = None
    e.corporate_address_id = None
    e.event_datetime = _EVENT_DT
    e.status = status
    e.budget_usd = budget_usd
    e.max_attendees = max_attendees
    e.auto_approve_rides = auto_approve_rides
    e.notes = None
    e.is_active = is_active
    e.created_at = _NOW
    e.updated_at = _NOW
    return e


def _make_attendee(
    attendee_id: int = 1,
    event_id: int = EVENT_ID,
    member_id: int | None = MEMBER_ID,
    ride_id: int | None = None,
    invited_by_id: int | None = ADMIN_ID,
    status: str = "invited",
    notes: str | None = None,
) -> CorporateEventAttendee:
    """Build a minimal CorporateEventAttendee instance for testing."""
    a = CorporateEventAttendee()
    a.id = attendee_id
    a.event_id = event_id
    a.member_id = member_id
    a.ride_id = ride_id
    a.invited_by_id = invited_by_id
    a.status = status
    a.notes = notes
    a.created_at = _NOW
    a.updated_at = _NOW
    return a


def _make_event_response(
    event_id: int = EVENT_ID,
    account_id: int = ACCOUNT_ID,
    status: str = "draft",
) -> EventResponse:
    return EventResponse(
        id=event_id,
        account_id=account_id,
        organizer_id=MEMBER_ID,
        created_by_id=MEMBER_ID,
        title="Q3 Team Offsite",
        description=None,
        event_location_name="Grand Hyatt NYC",
        event_address_line1=None,
        event_city=None,
        event_state=None,
        event_country="US",
        event_latitude=None,
        event_longitude=None,
        corporate_address_id=None,
        event_datetime=_EVENT_DT,
        status=status,
        budget_usd=None,
        max_attendees=None,
        auto_approve_rides=False,
        notes=None,
        is_active=True,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _make_attendee_response(
    attendee_id: int = 1,
    event_id: int = EVENT_ID,
    member_id: int | None = MEMBER_ID,
    status: str = "invited",
) -> AttendeeResponse:
    return AttendeeResponse(
        id=attendee_id,
        event_id=event_id,
        member_id=member_id,
        ride_id=None,
        invited_by_id=ADMIN_ID,
        status=status,
        notes=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _scalar_result(value) -> MagicMock:
    res = MagicMock()
    res.scalar_one_or_none.return_value = value
    return res


def _scalar_one_result(value) -> MagicMock:
    res = MagicMock()
    res.scalar_one.return_value = value
    return res


def _scalars_all_result(values: list) -> MagicMock:
    scalars = MagicMock()
    scalars.all.return_value = values
    res = MagicMock()
    res.scalars.return_value = scalars
    return res


def _mock_user(user_id: int = USER_ID) -> MagicMock:
    u = MagicMock()
    u.id = user_id
    return u


# ---------------------------------------------------------------------------
# 1. create_event — creates with draft status
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_event_draft_status():
    db = AsyncMock()
    added = []
    db.add = lambda x: added.append(x)

    async def _fake_refresh(obj):
        obj.id = EVENT_ID
        obj.event_latitude = None
        obj.event_longitude = None
        obj.created_at = _NOW
        obj.updated_at = _NOW

    db.refresh = _fake_refresh

    data = EventCreate(title="Q3 Team Offsite", event_location_name="Grand Hyatt NYC", event_datetime=_EVENT_DT)
    result = await create_event(db, ACCOUNT_ID, data, member_id=MEMBER_ID)

    assert len(added) == 1
    new_event = added[0]
    assert new_event.status == "draft"
    assert result.id == EVENT_ID


# ---------------------------------------------------------------------------
# 2. create_event — sets organizer_id and created_by_id to member_id
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_event_sets_organizer_and_created_by():
    db = AsyncMock()
    added = []
    db.add = lambda x: added.append(x)

    async def _fake_refresh(obj):
        obj.id = EVENT_ID
        obj.event_latitude = None
        obj.event_longitude = None
        obj.created_at = _NOW
        obj.updated_at = _NOW

    db.refresh = _fake_refresh

    data = EventCreate(title="Holiday Party", event_location_name="Company HQ", event_datetime=_EVENT_DT)
    await create_event(db, ACCOUNT_ID, data, member_id=MEMBER_ID)

    assert added[0].organizer_id == MEMBER_ID
    assert added[0].created_by_id == MEMBER_ID
    assert added[0].is_active is True


# ---------------------------------------------------------------------------
# 3. get_event — 404 when not found
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_event_404_when_not_found():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc:
        await get_event(db, ACCOUNT_ID, EVENT_ID)
    assert exc.value.status_code == 404
    assert "not found" in exc.value.detail.lower()


# ---------------------------------------------------------------------------
# 4. get_event — returns event when found
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_event_returns_when_found():
    db = AsyncMock()
    existing = _make_event(title="Client Dinner Downtown")
    db.execute.return_value = _scalar_result(existing)

    result = await get_event(db, ACCOUNT_ID, EVENT_ID)

    assert result.id == EVENT_ID
    assert result.title == "Client Dinner Downtown"
    assert result.account_id == ACCOUNT_ID


# ---------------------------------------------------------------------------
# 5. list_events — returns paginated list
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_events_returns_paginated():
    db = AsyncMock()
    items = [_make_event(event_id=1), _make_event(event_id=2)]
    items[1].id = 2

    db.execute.side_effect = [
        _scalar_one_result(2),
        _scalars_all_result(items),
    ]

    result = await list_events(db, ACCOUNT_ID, limit=50, offset=0)

    assert result.total == 2
    assert result.limit == 50
    assert result.offset == 0
    assert len(result.items) == 2


# ---------------------------------------------------------------------------
# 6. list_events — filters by status
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_events_filters_by_status():
    db = AsyncMock()
    active_event = _make_event(event_id=1, status="active")

    db.execute.side_effect = [
        _scalar_one_result(1),
        _scalars_all_result([active_event]),
    ]

    result = await list_events(db, ACCOUNT_ID, status="active", limit=50, offset=0)

    assert result.total == 1
    assert result.items[0].status == "active"


# ---------------------------------------------------------------------------
# 7. update_event — 404 when not found
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_event_404_when_not_found():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc:
        await update_event(
            db, ACCOUNT_ID, EVENT_ID,
            EventUpdate(title="New Title"),
            member_id=MEMBER_ID,
        )
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 8. update_event — 409 when cancelled
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_event_409_when_cancelled():
    db = AsyncMock()
    existing = _make_event(status="cancelled")
    db.execute.return_value = _scalar_result(existing)

    with pytest.raises(HTTPException) as exc:
        await update_event(
            db, ACCOUNT_ID, EVENT_ID,
            EventUpdate(title="New Title"),
            member_id=MEMBER_ID,
        )
    assert exc.value.status_code == 409
    assert "cancelled" in exc.value.detail.lower()


# ---------------------------------------------------------------------------
# 9. update_event — 409 when completed
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_event_409_when_completed():
    db = AsyncMock()
    existing = _make_event(status="completed")
    db.execute.return_value = _scalar_result(existing)

    with pytest.raises(HTTPException) as exc:
        await update_event(
            db, ACCOUNT_ID, EVENT_ID,
            EventUpdate(title="New Title"),
            member_id=MEMBER_ID,
        )
    assert exc.value.status_code == 409
    assert "completed" in exc.value.detail.lower()


# ---------------------------------------------------------------------------
# 10. update_event — partial update only writes supplied fields
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_event_partial_fields_only():
    db = AsyncMock()
    existing = _make_event(
        title="Old Title",
        description="Old description",
        status="draft",
    )
    db.execute.return_value = _scalar_result(existing)
    db.refresh = AsyncMock()

    data = EventUpdate(title="New Title")
    await update_event(db, ACCOUNT_ID, EVENT_ID, data, member_id=MEMBER_ID)

    assert existing.title == "New Title"
    assert existing.description == "Old description"   # unchanged
    assert existing.status == "draft"                  # unchanged


# ---------------------------------------------------------------------------
# 11. activate_event — 409 when not draft
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_activate_event_409_when_not_draft():
    db = AsyncMock()
    existing = _make_event(status="active")
    db.execute.return_value = _scalar_result(existing)

    with pytest.raises(HTTPException) as exc:
        await activate_event(db, ACCOUNT_ID, EVENT_ID)
    assert exc.value.status_code == 409
    assert "draft" in exc.value.detail.lower()


# ---------------------------------------------------------------------------
# 12. activate_event — success sets status to active
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_activate_event_success():
    db = AsyncMock()
    existing = _make_event(status="draft")
    db.execute.return_value = _scalar_result(existing)
    db.refresh = AsyncMock()

    result = await activate_event(db, ACCOUNT_ID, EVENT_ID)

    assert existing.status == "active"


# ---------------------------------------------------------------------------
# 13. cancel_event — 404 when not found
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cancel_event_404_when_not_found():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc:
        await cancel_event(db, ACCOUNT_ID, EVENT_ID)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 14. cancel_event — 409 when completed
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cancel_event_409_when_completed():
    db = AsyncMock()
    existing = _make_event(status="completed")
    db.execute.return_value = _scalar_result(existing)

    with pytest.raises(HTTPException) as exc:
        await cancel_event(db, ACCOUNT_ID, EVENT_ID)
    assert exc.value.status_code == 409
    assert "completed" in exc.value.detail.lower()


# ---------------------------------------------------------------------------
# 15. cancel_event — 409 when already cancelled
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cancel_event_409_when_already_cancelled():
    db = AsyncMock()
    existing = _make_event(status="cancelled")
    db.execute.return_value = _scalar_result(existing)

    with pytest.raises(HTTPException) as exc:
        await cancel_event(db, ACCOUNT_ID, EVENT_ID)
    assert exc.value.status_code == 409
    assert "already cancelled" in exc.value.detail.lower()


# ---------------------------------------------------------------------------
# 16. cancel_event — success sets status to cancelled
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cancel_event_success():
    db = AsyncMock()
    existing = _make_event(status="active")
    db.execute.return_value = _scalar_result(existing)
    db.refresh = AsyncMock()

    await cancel_event(db, ACCOUNT_ID, EVENT_ID)

    assert existing.status == "cancelled"


# ---------------------------------------------------------------------------
# 17. complete_event — 409 when not active
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_complete_event_409_when_not_active():
    db = AsyncMock()
    existing = _make_event(status="draft")
    db.execute.return_value = _scalar_result(existing)

    with pytest.raises(HTTPException) as exc:
        await complete_event(db, ACCOUNT_ID, EVENT_ID)
    assert exc.value.status_code == 409
    assert "active" in exc.value.detail.lower()


# ---------------------------------------------------------------------------
# 18. complete_event — success sets status to completed
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_complete_event_success():
    db = AsyncMock()
    existing = _make_event(status="active")
    db.execute.return_value = _scalar_result(existing)
    db.refresh = AsyncMock()

    await complete_event(db, ACCOUNT_ID, EVENT_ID)

    assert existing.status == "completed"


# ---------------------------------------------------------------------------
# 19. invite_attendees — 404 when event not found
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_invite_attendees_404_when_event_not_found():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc:
        await invite_attendees(db, ACCOUNT_ID, EVENT_ID, [5, 6], invited_by_id=ADMIN_ID)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 20. invite_attendees — 409 when event cancelled
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_invite_attendees_409_when_event_cancelled():
    db = AsyncMock()
    existing = _make_event(status="cancelled")
    db.execute.return_value = _scalar_result(existing)

    with pytest.raises(HTTPException) as exc:
        await invite_attendees(db, ACCOUNT_ID, EVENT_ID, [5], invited_by_id=ADMIN_ID)
    assert exc.value.status_code == 409
    assert "cancelled" in exc.value.detail.lower()


# ---------------------------------------------------------------------------
# 21. invite_attendees — skips duplicate member silently
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_invite_attendees_skips_duplicate():
    db = AsyncMock()
    existing_event = _make_event(status="active")
    existing_attendee = _make_attendee(member_id=5)

    added = []
    db.add = lambda x: added.append(x)

    db.execute.side_effect = [
        _scalar_result(existing_event),   # fetch event
        _scalar_result(existing_attendee),  # duplicate check for member 5
        _scalar_one_result(1),             # count attendees
        _scalars_all_result([existing_attendee]),  # list attendees
    ]

    result = await invite_attendees(db, ACCOUNT_ID, EVENT_ID, [5], invited_by_id=ADMIN_ID)

    assert len(added) == 0  # no new records inserted


# ---------------------------------------------------------------------------
# 22. invite_attendees — inserts new attendees with invited status
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_invite_attendees_inserts_new():
    db = AsyncMock()
    existing_event = _make_event(status="active")
    new_attendee = _make_attendee(member_id=7)

    added = []
    db.add = lambda x: added.append(x)

    db.execute.side_effect = [
        _scalar_result(existing_event),   # fetch event
        _scalar_result(None),              # duplicate check — not found
        _scalar_one_result(1),             # count
        _scalars_all_result([new_attendee]),  # list
    ]

    await invite_attendees(db, ACCOUNT_ID, EVENT_ID, [7], invited_by_id=ADMIN_ID)

    assert len(added) == 1
    assert added[0].status == "invited"
    assert added[0].member_id == 7


# ---------------------------------------------------------------------------
# 23. update_attendee_status — 404 when event not found
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_attendee_status_404_when_event_not_found():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc:
        await update_attendee_status(db, ACCOUNT_ID, EVENT_ID, MEMBER_ID, "confirmed")
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 24. update_attendee_status — 404 when attendee not found
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_attendee_status_404_when_attendee_not_found():
    db = AsyncMock()
    existing_event = _make_event(status="active")

    db.execute.side_effect = [
        _scalar_result(existing_event),  # fetch event
        _scalar_result(None),            # attendee lookup
    ]

    with pytest.raises(HTTPException) as exc:
        await update_attendee_status(db, ACCOUNT_ID, EVENT_ID, MEMBER_ID, "confirmed")
    assert exc.value.status_code == 404
    assert "attendee" in exc.value.detail.lower()


# ---------------------------------------------------------------------------
# 25. update_attendee_status — success updates status
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_attendee_status_success():
    db = AsyncMock()
    existing_event = _make_event(status="active")
    existing_attendee = _make_attendee(status="invited")

    db.execute.side_effect = [
        _scalar_result(existing_event),
        _scalar_result(existing_attendee),
    ]
    db.refresh = AsyncMock()

    result = await update_attendee_status(db, ACCOUNT_ID, EVENT_ID, MEMBER_ID, "confirmed")

    assert existing_attendee.status == "confirmed"


# ---------------------------------------------------------------------------
# 26. get_event_summary — 404 when not found
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_event_summary_404_when_not_found():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc:
        await get_event_summary(db, ACCOUNT_ID, EVENT_ID)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 27. get_event_summary — returns correct counts
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_event_summary_returns_correct_counts():
    db = AsyncMock()
    existing = _make_event(title="Annual Conference", status="active", budget_usd=Decimal("5000.00"))
    a1 = _make_attendee(attendee_id=1, status="invited")
    a2 = _make_attendee(attendee_id=2, status="confirmed", ride_id=RIDE_ID)
    a3 = _make_attendee(attendee_id=3, status="declined")

    db.execute.side_effect = [
        _scalar_result(existing),
        _scalars_all_result([a1, a2, a3]),
    ]

    result = await get_event_summary(db, ACCOUNT_ID, EVENT_ID)

    assert result.event_id == EVENT_ID
    assert result.total_invited == 1
    assert result.total_confirmed == 1
    assert result.total_declined == 1
    assert result.total_cancelled == 0
    assert result.rides_linked == 1
    assert result.budget_usd == Decimal("5000.00")


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


def test_event_create_required_fields():
    """28. EventCreate — title and event_location_name required."""
    with pytest.raises(ValidationError):
        EventCreate()

    with pytest.raises(ValidationError):
        EventCreate(title="Party", event_datetime=_EVENT_DT)  # missing event_location_name

    valid = EventCreate(
        title="Party",
        event_location_name="Office",
        event_datetime=_EVENT_DT,
    )
    assert valid.title == "Party"


def test_event_create_optional_defaults():
    """29. EventCreate — optional fields default correctly."""
    data = EventCreate(
        title="Offsite",
        event_location_name="Venue",
        event_datetime=_EVENT_DT,
    )
    assert data.description is None
    assert data.auto_approve_rides is False
    assert data.budget_usd is None
    assert data.max_attendees is None


def test_event_update_all_optional():
    """30. EventUpdate — all fields optional."""
    data = EventUpdate()
    assert data.title is None
    assert data.event_location_name is None
    assert data.event_datetime is None
    assert data.auto_approve_rides is None


def test_invite_attendees_request_min_length():
    """31. InviteAttendeesRequest — member_ids min length 1."""
    with pytest.raises(ValidationError):
        InviteAttendeesRequest(member_ids=[])


def test_invite_attendees_request_max_length():
    """32. InviteAttendeesRequest — member_ids max length 50."""
    with pytest.raises(ValidationError):
        InviteAttendeesRequest(member_ids=list(range(51)))

    valid = InviteAttendeesRequest(member_ids=list(range(50)))
    assert len(valid.member_ids) == 50


def test_event_response_from_attributes():
    """33. EventResponse — from_attributes construction."""
    resp = _make_event_response()
    assert resp.id == EVENT_ID
    assert resp.account_id == ACCOUNT_ID
    assert resp.title == "Q3 Team Offsite"
    assert resp.status == "draft"
    assert resp.is_active is True
    assert isinstance(resp.created_at, datetime)
    assert resp.auto_approve_rides is False


def test_attendee_response_from_attributes():
    """34. AttendeeResponse — from_attributes construction."""
    resp = _make_attendee_response()
    assert resp.id == 1
    assert resp.event_id == EVENT_ID
    assert resp.member_id == MEMBER_ID
    assert resp.status == "invited"
    assert isinstance(resp.created_at, datetime)


def test_event_summary_response_construction():
    """35. EventSummaryResponse — construction."""
    summary = EventSummaryResponse(
        event_id=EVENT_ID,
        total_invited=5,
        total_confirmed=3,
        total_declined=1,
        total_cancelled=0,
        rides_linked=2,
        budget_usd=Decimal("2500.00"),
    )
    assert summary.event_id == EVENT_ID
    assert summary.total_invited == 5
    assert summary.rides_linked == 2


# ---------------------------------------------------------------------------
# API layer tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_create_event_201():
    """36. POST create — 201 member can create."""
    from app.api.v1.corporate_events import create_my_event

    user = _mock_user(MEMBER_ID)
    db = AsyncMock()
    data = EventCreate(title="Q3 Team Offsite", event_location_name="Grand Hyatt NYC", event_datetime=_EVENT_DT)
    mock_resp = _make_event_response()

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(f"{_ROUTER}.create_event", new=AsyncMock(return_value=mock_resp)),
    ):
        result = await create_my_event(data=data, user=user, db=db)

    assert result.id == EVENT_ID
    assert result.status == "draft"


@pytest.mark.asyncio
async def test_api_create_event_404_no_account():
    """37. POST create — 404 when no corporate account."""
    from app.api.v1.corporate_events import create_my_event

    user = _mock_user(MEMBER_ID)
    db = AsyncMock()
    data = EventCreate(title="Party", event_location_name="HQ", event_datetime=_EVENT_DT)

    with patch(
        f"{_ROUTER}._resolve_account_id",
        new=AsyncMock(side_effect=HTTPException(status_code=404, detail="No account")),
    ):
        with pytest.raises(HTTPException) as exc:
            await create_my_event(data=data, user=user, db=db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_api_list_events_200():
    """38. GET list — 200 member can list."""
    from app.api.v1.corporate_events import list_my_events

    user = _mock_user(MEMBER_ID)
    db = AsyncMock()
    mock_resp = EventListResponse(
        total=1, limit=50, offset=0,
        items=[_make_event_response()],
    )

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(f"{_ROUTER}.list_events", new=AsyncMock(return_value=mock_resp)),
    ):
        result = await list_my_events(status=None, limit=50, offset=0, user=user, db=db)

    assert result.total == 1
    assert len(result.items) == 1


@pytest.mark.asyncio
async def test_api_get_event_200():
    """39. GET get — 200 member can view."""
    from app.api.v1.corporate_events import get_my_event

    user = _mock_user(MEMBER_ID)
    db = AsyncMock()
    mock_resp = _make_event_response()

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(f"{_ROUTER}.get_event", new=AsyncMock(return_value=mock_resp)),
    ):
        result = await get_my_event(event_id=EVENT_ID, user=user, db=db)

    assert result.id == EVENT_ID


@pytest.mark.asyncio
async def test_api_get_event_404():
    """40. GET get — 404 not found."""
    from app.api.v1.corporate_events import get_my_event

    user = _mock_user(MEMBER_ID)
    db = AsyncMock()

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(
            f"{_ROUTER}.get_event",
            new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Not found")),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await get_my_event(event_id=EVENT_ID, user=user, db=db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_api_update_event_200():
    """41. PUT update — 200 member can update."""
    from app.api.v1.corporate_events import update_my_event

    user = _mock_user(MEMBER_ID)
    db = AsyncMock()
    data = EventUpdate(title="Updated Title")
    mock_resp = _make_event_response()

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(f"{_ROUTER}.update_event", new=AsyncMock(return_value=mock_resp)),
    ):
        result = await update_my_event(event_id=EVENT_ID, data=data, user=user, db=db)

    assert result.id == EVENT_ID


@pytest.mark.asyncio
async def test_api_update_event_409_cancelled_or_completed():
    """42. PUT update — 409 when cancelled or completed."""
    from app.api.v1.corporate_events import update_my_event

    user = _mock_user(MEMBER_ID)
    db = AsyncMock()
    data = EventUpdate(title="New Title")

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(
            f"{_ROUTER}.update_event",
            new=AsyncMock(
                side_effect=HTTPException(
                    status_code=409, detail="Cannot update a cancelled or completed event."
                )
            ),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await update_my_event(event_id=EVENT_ID, data=data, user=user, db=db)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_api_get_summary_200():
    """43. GET summary — 200 member can view summary."""
    from app.api.v1.corporate_events import get_my_event_summary

    user = _mock_user(MEMBER_ID)
    db = AsyncMock()
    mock_resp = EventSummaryResponse(
        event_id=EVENT_ID,
        total_invited=3,
        total_confirmed=2,
        total_declined=1,
        total_cancelled=0,
        rides_linked=2,
        budget_usd=None,
    )

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(f"{_ROUTER}.get_event_summary", new=AsyncMock(return_value=mock_resp)),
    ):
        result = await get_my_event_summary(event_id=EVENT_ID, user=user, db=db)

    assert result.event_id == EVENT_ID
    assert result.total_confirmed == 2


@pytest.mark.asyncio
async def test_api_activate_event_403_non_admin():
    """44. POST activate — 403 non-admin cannot activate."""
    from app.api.v1.corporate_events import activate_my_event

    user = _mock_user(MEMBER_ID)
    db = AsyncMock()

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(
            f"{_ROUTER}._require_account_admin",
            new=AsyncMock(side_effect=HTTPException(status_code=403, detail="Forbidden")),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await activate_my_event(event_id=EVENT_ID, user=user, db=db)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_api_activate_event_200():
    """45. POST activate — 200 admin can activate."""
    from app.api.v1.corporate_events import activate_my_event

    user = _mock_user(ADMIN_ID)
    db = AsyncMock()
    mock_resp = _make_event_response(status="active")

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
        patch(f"{_ROUTER}.activate_event", new=AsyncMock(return_value=mock_resp)),
    ):
        result = await activate_my_event(event_id=EVENT_ID, user=user, db=db)

    assert result.status == "active"


@pytest.mark.asyncio
async def test_api_cancel_event_200():
    """46. POST cancel — 200 admin can cancel."""
    from app.api.v1.corporate_events import cancel_my_event

    user = _mock_user(ADMIN_ID)
    db = AsyncMock()
    mock_resp = _make_event_response(status="cancelled")

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
        patch(f"{_ROUTER}.cancel_event", new=AsyncMock(return_value=mock_resp)),
    ):
        result = await cancel_my_event(event_id=EVENT_ID, user=user, db=db)

    assert result.status == "cancelled"


@pytest.mark.asyncio
async def test_api_cancel_event_403_non_admin():
    """47. POST cancel — 403 non-admin cannot cancel."""
    from app.api.v1.corporate_events import cancel_my_event

    user = _mock_user(MEMBER_ID)
    db = AsyncMock()

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(
            f"{_ROUTER}._require_account_admin",
            new=AsyncMock(side_effect=HTTPException(status_code=403, detail="Forbidden")),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await cancel_my_event(event_id=EVENT_ID, user=user, db=db)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_api_complete_event_200():
    """48. POST complete — 200 admin can complete."""
    from app.api.v1.corporate_events import complete_my_event

    user = _mock_user(ADMIN_ID)
    db = AsyncMock()
    mock_resp = _make_event_response(status="completed")

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
        patch(f"{_ROUTER}.complete_event", new=AsyncMock(return_value=mock_resp)),
    ):
        result = await complete_my_event(event_id=EVENT_ID, user=user, db=db)

    assert result.status == "completed"


@pytest.mark.asyncio
async def test_api_invite_attendees_200():
    """49. POST invite — 200 admin can invite attendees."""
    from app.api.v1.corporate_events import invite_event_attendees

    user = _mock_user(ADMIN_ID)
    db = AsyncMock()
    data = InviteAttendeesRequest(member_ids=[5, 6, 7])
    mock_resp = AttendeeListResponse(
        total=3, limit=3, offset=0,
        items=[
            _make_attendee_response(attendee_id=1, member_id=5),
            _make_attendee_response(attendee_id=2, member_id=6),
            _make_attendee_response(attendee_id=3, member_id=7),
        ],
    )

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
        patch(f"{_ROUTER}.invite_attendees", new=AsyncMock(return_value=mock_resp)),
    ):
        result = await invite_event_attendees(event_id=EVENT_ID, data=data, user=user, db=db)

    assert result.total == 3
    assert len(result.items) == 3


@pytest.mark.asyncio
async def test_api_invite_attendees_403_non_admin():
    """50. POST invite — 403 non-admin cannot invite."""
    from app.api.v1.corporate_events import invite_event_attendees

    user = _mock_user(MEMBER_ID)
    db = AsyncMock()
    data = InviteAttendeesRequest(member_ids=[5])

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(
            f"{_ROUTER}._require_account_admin",
            new=AsyncMock(side_effect=HTTPException(status_code=403, detail="Forbidden")),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await invite_event_attendees(event_id=EVENT_ID, data=data, user=user, db=db)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_api_update_attendee_status_200():
    """51. PATCH attendee status — 200 admin can update."""
    from app.api.v1.corporate_events import update_event_attendee_status

    user = _mock_user(ADMIN_ID)
    db = AsyncMock()
    data = AttendeeStatusUpdate(status="confirmed")
    mock_resp = _make_attendee_response(status="confirmed")

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
        patch(f"{_ROUTER}.update_attendee_status", new=AsyncMock(return_value=mock_resp)),
    ):
        result = await update_event_attendee_status(
            event_id=EVENT_ID, member_id=MEMBER_ID, data=data, user=user, db=db
        )

    assert result.status == "confirmed"


@pytest.mark.asyncio
async def test_api_platform_list_all_200():
    """52. GET platform list — 200 platform-admin list."""
    from app.api.v1.corporate_events import admin_list_all_events

    admin = _mock_user(ADMIN_ID)
    db = AsyncMock()
    mock_resp = EventListResponse(
        total=2, limit=50, offset=0,
        items=[
            _make_event_response(event_id=1, account_id=10),
            _make_event_response(event_id=2, account_id=11),
        ],
    )

    with patch(f"{_ROUTER}.list_all_events_platform", new=AsyncMock(return_value=mock_resp)):
        result = await admin_list_all_events(limit=50, offset=0, _admin=admin, db=db)

    assert result.total == 2
    assert len(result.items) == 2


@pytest.mark.asyncio
async def test_api_platform_account_list_200():
    """53. GET platform account list — 200 platform-admin account-specific list."""
    from app.api.v1.corporate_events import admin_list_account_events

    admin = _mock_user(ADMIN_ID)
    db = AsyncMock()
    mock_resp = EventListResponse(
        total=1, limit=50, offset=0,
        items=[_make_event_response()],
    )

    with patch(f"{_ROUTER}.list_events", new=AsyncMock(return_value=mock_resp)):
        result = await admin_list_account_events(
            account_id=ACCOUNT_ID, status=None, limit=50, offset=0,
            _admin=admin, db=db,
        )

    assert result.total == 1
    assert result.items[0].account_id == ACCOUNT_ID
