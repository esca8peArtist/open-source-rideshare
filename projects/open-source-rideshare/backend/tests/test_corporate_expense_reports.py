"""Tests for the Corporate Expense Reports feature.

Service tests (async, mocked DB):
  1.  submit_expense_report — success
  2.  submit_expense_report — non-member → 403
  3.  submit_expense_report — ride belongs to other user → 403
  4.  submit_expense_report — bad cost_center_id → 404
  5.  submit_expense_report — bad trip_purpose_id → 404
  6.  get_expense_report — success by submitter
  7.  get_expense_report — success by admin
  8.  get_expense_report — wrong account → 404
  9.  get_expense_report — forbidden for other member → 403
  10. list_my_expense_reports — returns own only
  11. list_my_expense_reports — status_filter works
  12. list_my_expense_reports — empty list
  13. list_account_expense_reports — admin success
  14. list_account_expense_reports — non-admin → 403
  15. list_account_expense_reports — status_filter works
  16. review_expense_report — approve success
  17. review_expense_report — reject success
  18. review_expense_report — already reviewed → 409
  19. review_expense_report — non-admin → 403
  20. withdraw_expense_report — success
  21. withdraw_expense_report — non-pending → 409
  22. withdraw_expense_report — wrong submitter → 403

Schema tests (sync):
  23. ExpenseReportCreate — valid
  24. ExpenseReportCreate — amount_usd ≤ 0 → ValidationError
  25. ExpenseReportReview — valid approve
  26. ExpenseReportReview — valid reject
  27. ExpenseReportReview — invalid action → ValidationError

API layer tests (service patched):
  28. POST /expense-reports → 201
  29. GET  /expense-reports → 200
  30. GET  /expense-reports/all → 200
  31. GET  /expense-reports/{id} → 200
  32. DELETE /expense-reports/{id}/withdraw → 200
  33. POST /expense-reports/{id}/review → 200
  34. GET  /admin/.../expense-reports → 200
  35. POST /expense-reports — no account → 404
  36. submit with ride from other user — 403 passthrough
  37. GET /expense-reports/{id} — forbidden → 403 passthrough
  38. review already reviewed → 409 passthrough
  39. withdraw non-pending → 409 passthrough
  40. list_account_expense_reports non-admin → 403 passthrough
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.corporate import BusinessAccountMember, MemberRole
from app.models.corporate_expense_report import CorporateExpenseReport, ExpenseStatus
from app.schemas.corporate_expense_report import (
    ExpenseReportCreate,
    ExpenseReportListResponse,
    ExpenseReportResponse,
    ExpenseReportReview,
)
from app.services.corporate_expense_report import (
    get_expense_report,
    list_account_expense_reports,
    list_my_expense_reports,
    review_expense_report,
    submit_expense_report,
    withdraw_expense_report,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
ACCOUNT_ID = 1
ADMIN_ID = 10
MEMBER_ID = 20
OTHER_USER_ID = 30
REPORT_ID = 100
RIDE_ID = 200
CC_ID = 5
TP_ID = 6


def _make_member(user_id: int, role: MemberRole = MemberRole.ADMIN) -> BusinessAccountMember:
    m = MagicMock(spec=BusinessAccountMember)
    m.account_id = ACCOUNT_ID
    m.user_id = user_id
    m.role = role
    m.is_active = True
    return m


def _make_report(
    report_id: int = REPORT_ID,
    submitted_by_id: int = MEMBER_ID,
    status: ExpenseStatus = ExpenseStatus.PENDING,
    ride_id: int | None = None,
) -> CorporateExpenseReport:
    r = MagicMock(spec=CorporateExpenseReport)
    r.id = report_id
    r.account_id = ACCOUNT_ID
    r.submitted_by_id = submitted_by_id
    r.ride_id = ride_id
    r.amount_usd = Decimal("75.00")
    r.description = "Client meeting ride"
    r.cost_center_id = None
    r.trip_purpose_id = None
    r.receipt_url = None
    r.status = status
    r.reviewed_by_id = None
    r.reviewed_at = None
    r.review_note = None
    r.submitted_at = NOW
    r.created_at = NOW
    return r


def _make_ride(rider_id: int = MEMBER_ID):
    ride = MagicMock()
    ride.id = RIDE_ID
    ride.rider_id = rider_id
    return ride


def _db_one(obj):
    """Return a mock execute result with scalar_one_or_none() → obj."""
    r = MagicMock()
    r.scalar_one_or_none.return_value = obj
    r.scalar_one.return_value = 1 if obj is not None else 0
    r.scalars.return_value.all.return_value = [obj] if obj is not None else []
    r.all.return_value = [obj] if obj is not None else []
    return r


def _db_none():
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    r.scalar_one.return_value = 0
    r.scalars.return_value.all.return_value = []
    r.all.return_value = []
    return r


def _db_list(items):
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    r.scalar_one.return_value = len(items)
    r.scalars.return_value.all.return_value = items
    r.all.return_value = items
    return r


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_expense_report_success():
    """1. submit_expense_report — success."""
    db = AsyncMock()
    member = _make_member(MEMBER_ID, MemberRole.MEMBER)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _db_one(member)
        return _db_none()

    db.execute = fake_execute
    db.flush = AsyncMock()

    def _set_id(obj):
        obj.id = REPORT_ID
        obj.submitted_at = NOW
        obj.created_at = NOW

    db.add = MagicMock(side_effect=_set_id)

    data = ExpenseReportCreate(amount_usd=Decimal("75.00"), description="Client meeting")
    result = await submit_expense_report(db, ACCOUNT_ID, MEMBER_ID, data)

    assert result.account_id == ACCOUNT_ID
    assert result.submitted_by_id == MEMBER_ID


@pytest.mark.asyncio
async def test_submit_expense_report_non_member():
    """2. submit_expense_report — non-member → 403."""
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_db_none())

    with pytest.raises(HTTPException) as exc:
        await submit_expense_report(
            db, ACCOUNT_ID, OTHER_USER_ID,
            ExpenseReportCreate(amount_usd=Decimal("10.00"), description="X"),
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_submit_expense_report_ride_other_user():
    """3. submit_expense_report — ride belongs to other user → 403."""
    db = AsyncMock()
    member = _make_member(MEMBER_ID, MemberRole.MEMBER)
    ride = _make_ride(rider_id=OTHER_USER_ID)  # different rider
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _db_one(member)
        return _db_one(ride)

    db.execute = fake_execute

    with pytest.raises(HTTPException) as exc:
        await submit_expense_report(
            db, ACCOUNT_ID, MEMBER_ID,
            ExpenseReportCreate(
                amount_usd=Decimal("50.00"), description="X", ride_id=RIDE_ID
            ),
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_submit_expense_report_bad_cost_center():
    """4. submit_expense_report — bad cost_center_id → 404."""
    db = AsyncMock()
    member = _make_member(MEMBER_ID, MemberRole.MEMBER)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _db_one(member)
        return _db_none()  # cost center not found

    db.execute = fake_execute

    with pytest.raises(HTTPException) as exc:
        await submit_expense_report(
            db, ACCOUNT_ID, MEMBER_ID,
            ExpenseReportCreate(
                amount_usd=Decimal("50.00"), description="X", cost_center_id=999
            ),
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_submit_expense_report_bad_trip_purpose():
    """5. submit_expense_report — bad trip_purpose_id → 404."""
    db = AsyncMock()
    member = _make_member(MEMBER_ID, MemberRole.MEMBER)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _db_one(member)
        return _db_none()  # trip purpose not found

    db.execute = fake_execute

    with pytest.raises(HTTPException) as exc:
        await submit_expense_report(
            db, ACCOUNT_ID, MEMBER_ID,
            ExpenseReportCreate(
                amount_usd=Decimal("50.00"), description="X", trip_purpose_id=999
            ),
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_expense_report_success_by_submitter():
    """6. get_expense_report — success by submitter."""
    db = AsyncMock()
    report = _make_report(submitted_by_id=MEMBER_ID)
    db.execute = AsyncMock(return_value=_db_one(report))

    result = await get_expense_report(db, ACCOUNT_ID, REPORT_ID, MEMBER_ID)
    assert result.id == REPORT_ID


@pytest.mark.asyncio
async def test_get_expense_report_success_by_admin():
    """7. get_expense_report — success by admin."""
    db = AsyncMock()
    report = _make_report(submitted_by_id=MEMBER_ID)
    admin_member = _make_member(ADMIN_ID, MemberRole.ADMIN)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _db_one(report)
        return _db_one(admin_member)

    db.execute = fake_execute

    result = await get_expense_report(db, ACCOUNT_ID, REPORT_ID, ADMIN_ID)
    assert result.id == REPORT_ID


@pytest.mark.asyncio
async def test_get_expense_report_wrong_account():
    """8. get_expense_report — wrong account → 404."""
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_db_none())

    with pytest.raises(HTTPException) as exc:
        await get_expense_report(db, ACCOUNT_ID, 999, MEMBER_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_expense_report_forbidden_other_member():
    """9. get_expense_report — forbidden for other member → 403."""
    db = AsyncMock()
    report = _make_report(submitted_by_id=MEMBER_ID)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _db_one(report)
        return _db_none()  # not an admin

    db.execute = fake_execute

    with pytest.raises(HTTPException) as exc:
        await get_expense_report(db, ACCOUNT_ID, REPORT_ID, OTHER_USER_ID)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_list_my_expense_reports_returns_own():
    """10. list_my_expense_reports — returns own only."""
    db = AsyncMock()
    report = _make_report(submitted_by_id=MEMBER_ID)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            r = MagicMock()
            r.scalar_one.return_value = 1
            return r
        return _db_list([report])

    db.execute = fake_execute

    result = await list_my_expense_reports(db, ACCOUNT_ID, MEMBER_ID)
    assert result.total == 1
    assert len(result.reports) == 1


@pytest.mark.asyncio
async def test_list_my_expense_reports_status_filter():
    """11. list_my_expense_reports — status_filter works."""
    db = AsyncMock()
    report = _make_report(submitted_by_id=MEMBER_ID, status=ExpenseStatus.APPROVED)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            r = MagicMock()
            r.scalar_one.return_value = 1
            return r
        return _db_list([report])

    db.execute = fake_execute

    result = await list_my_expense_reports(
        db, ACCOUNT_ID, MEMBER_ID, status_filter="approved"
    )
    assert result.total == 1
    assert result.reports[0].status == "approved"


@pytest.mark.asyncio
async def test_list_my_expense_reports_empty():
    """12. list_my_expense_reports — empty list."""
    db = AsyncMock()
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            r = MagicMock()
            r.scalar_one.return_value = 0
            return r
        return _db_list([])

    db.execute = fake_execute

    result = await list_my_expense_reports(db, ACCOUNT_ID, MEMBER_ID)
    assert result.total == 0
    assert result.reports == []


@pytest.mark.asyncio
async def test_list_account_expense_reports_admin_success():
    """13. list_account_expense_reports — admin success."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID, MemberRole.ADMIN)
    report = _make_report()
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _db_one(admin)
        if call_count == 2:
            r = MagicMock()
            r.scalar_one.return_value = 1
            return r
        return _db_list([report])

    db.execute = fake_execute

    result = await list_account_expense_reports(db, ACCOUNT_ID, ADMIN_ID)
    assert result.total == 1


@pytest.mark.asyncio
async def test_list_account_expense_reports_non_admin():
    """14. list_account_expense_reports — non-admin → 403."""
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_db_none())

    with pytest.raises(HTTPException) as exc:
        await list_account_expense_reports(db, ACCOUNT_ID, MEMBER_ID)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_list_account_expense_reports_status_filter():
    """15. list_account_expense_reports — status_filter works."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID, MemberRole.ADMIN)
    report = _make_report(status=ExpenseStatus.REJECTED)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _db_one(admin)
        if call_count == 2:
            r = MagicMock()
            r.scalar_one.return_value = 1
            return r
        return _db_list([report])

    db.execute = fake_execute

    result = await list_account_expense_reports(
        db, ACCOUNT_ID, ADMIN_ID, status_filter="rejected"
    )
    assert result.total == 1
    assert result.reports[0].status == "rejected"


@pytest.mark.asyncio
async def test_review_expense_report_approve():
    """16. review_expense_report — approve success."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID, MemberRole.ADMIN)
    report = _make_report(status=ExpenseStatus.PENDING)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _db_one(admin)
        return _db_one(report)

    db.execute = fake_execute
    db.flush = AsyncMock()

    data = ExpenseReportReview(action="approved", review_note="Looks good")
    result = await review_expense_report(db, ACCOUNT_ID, REPORT_ID, ADMIN_ID, data)

    assert report.status == ExpenseStatus.APPROVED
    assert report.reviewed_by_id == ADMIN_ID
    assert report.review_note == "Looks good"


@pytest.mark.asyncio
async def test_review_expense_report_reject():
    """17. review_expense_report — reject success."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID, MemberRole.ADMIN)
    report = _make_report(status=ExpenseStatus.PENDING)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _db_one(admin)
        return _db_one(report)

    db.execute = fake_execute
    db.flush = AsyncMock()

    data = ExpenseReportReview(action="rejected", review_note="Missing receipt")
    result = await review_expense_report(db, ACCOUNT_ID, REPORT_ID, ADMIN_ID, data)

    assert report.status == ExpenseStatus.REJECTED


@pytest.mark.asyncio
async def test_review_expense_report_already_reviewed():
    """18. review_expense_report — already reviewed → 409."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID, MemberRole.ADMIN)
    report = _make_report(status=ExpenseStatus.APPROVED)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _db_one(admin)
        return _db_one(report)

    db.execute = fake_execute

    with pytest.raises(HTTPException) as exc:
        await review_expense_report(
            db, ACCOUNT_ID, REPORT_ID, ADMIN_ID,
            ExpenseReportReview(action="rejected"),
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_review_expense_report_non_admin():
    """19. review_expense_report — non-admin → 403."""
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_db_none())

    with pytest.raises(HTTPException) as exc:
        await review_expense_report(
            db, ACCOUNT_ID, REPORT_ID, MEMBER_ID,
            ExpenseReportReview(action="approved"),
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_withdraw_expense_report_success():
    """20. withdraw_expense_report — success."""
    db = AsyncMock()
    report = _make_report(submitted_by_id=MEMBER_ID, status=ExpenseStatus.PENDING)
    db.execute = AsyncMock(return_value=_db_one(report))
    db.flush = AsyncMock()

    result = await withdraw_expense_report(db, ACCOUNT_ID, REPORT_ID, MEMBER_ID)

    assert report.status == ExpenseStatus.WITHDRAWN


@pytest.mark.asyncio
async def test_withdraw_expense_report_non_pending():
    """21. withdraw_expense_report — non-pending → 409."""
    db = AsyncMock()
    report = _make_report(submitted_by_id=MEMBER_ID, status=ExpenseStatus.APPROVED)
    db.execute = AsyncMock(return_value=_db_one(report))

    with pytest.raises(HTTPException) as exc:
        await withdraw_expense_report(db, ACCOUNT_ID, REPORT_ID, MEMBER_ID)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_withdraw_expense_report_wrong_submitter():
    """22. withdraw_expense_report — wrong submitter → 403."""
    db = AsyncMock()
    report = _make_report(submitted_by_id=MEMBER_ID, status=ExpenseStatus.PENDING)
    db.execute = AsyncMock(return_value=_db_one(report))

    with pytest.raises(HTTPException) as exc:
        await withdraw_expense_report(db, ACCOUNT_ID, REPORT_ID, OTHER_USER_ID)
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_expense_report_create_valid():
    """23. ExpenseReportCreate — valid."""
    data = ExpenseReportCreate(amount_usd=Decimal("50.00"), description="Airport taxi")
    assert data.amount_usd == Decimal("50.00")
    assert data.description == "Airport taxi"
    assert data.ride_id is None
    assert data.receipt_url is None


def test_expense_report_create_amount_zero():
    """24. ExpenseReportCreate — amount_usd = 0 → ValidationError."""
    with pytest.raises(ValidationError):
        ExpenseReportCreate(amount_usd=Decimal("0"), description="X")


def test_expense_report_create_amount_negative():
    """24b. ExpenseReportCreate — amount_usd < 0 → ValidationError."""
    with pytest.raises(ValidationError):
        ExpenseReportCreate(amount_usd=Decimal("-10.00"), description="X")


def test_expense_report_review_valid_approve():
    """25. ExpenseReportReview — valid approve."""
    data = ExpenseReportReview(action="approved", review_note="OK")
    assert data.action == "approved"
    assert data.review_note == "OK"


def test_expense_report_review_valid_reject():
    """26. ExpenseReportReview — valid reject."""
    data = ExpenseReportReview(action="rejected")
    assert data.action == "rejected"
    assert data.review_note is None


def test_expense_report_review_invalid_action():
    """27. ExpenseReportReview — invalid action → ValidationError."""
    with pytest.raises(ValidationError):
        ExpenseReportReview(action="withdrawn")


# ---------------------------------------------------------------------------
# API layer tests (service patched)
# ---------------------------------------------------------------------------


def _make_report_response(report_id: int = REPORT_ID) -> ExpenseReportResponse:
    return ExpenseReportResponse(
        id=report_id,
        account_id=ACCOUNT_ID,
        submitted_by_id=MEMBER_ID,
        ride_id=None,
        amount_usd=Decimal("75.00"),
        description="Client meeting",
        cost_center_id=None,
        trip_purpose_id=None,
        receipt_url=None,
        status="pending",
        reviewed_by_id=None,
        reviewed_at=None,
        review_note=None,
        submitted_at=NOW,
        created_at=NOW,
    )


def _make_list_response() -> ExpenseReportListResponse:
    return ExpenseReportListResponse(
        account_id=ACCOUNT_ID,
        total=0,
        reports=[],
    )


def _fake_user_deps(user_id: int = ADMIN_ID):
    from app.models.user import User as UserModel
    u = MagicMock(spec=UserModel)
    u.id = user_id
    u.is_admin = True

    async def _fake_db():
        db = AsyncMock()
        yield db

    return u, _fake_db


@pytest.mark.asyncio
async def test_api_submit_expense_report():
    """28. POST /corporate/accounts/me/expense-reports → 201."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    fake_user, fake_db = _fake_user_deps(MEMBER_ID)
    report_response = _make_report_response()

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with (
        patch(
            "app.api.v1.corporate_expense_reports.get_user_account",
            new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID)),
        ),
        patch(
            "app.api.v1.corporate_expense_reports.submit_expense_report",
            new=AsyncMock(return_value=report_response),
        ),
        TestClient(app) as client,
    ):
        resp = client.post(
            "/api/v1/corporate/accounts/me/expense-reports",
            json={"amount_usd": "75.00", "description": "Client meeting"},
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 201
    assert resp.json()["id"] == REPORT_ID


@pytest.mark.asyncio
async def test_api_list_my_expense_reports():
    """29. GET /corporate/accounts/me/expense-reports → 200."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    fake_user, fake_db = _fake_user_deps(MEMBER_ID)
    list_response = _make_list_response()

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with (
        patch(
            "app.api.v1.corporate_expense_reports.get_user_account",
            new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID)),
        ),
        patch(
            "app.api.v1.corporate_expense_reports.list_my_expense_reports",
            new=AsyncMock(return_value=list_response),
        ),
        TestClient(app) as client,
    ):
        resp = client.get("/api/v1/corporate/accounts/me/expense-reports")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_api_list_all_expense_reports():
    """30. GET /corporate/accounts/me/expense-reports/all → 200."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    fake_user, fake_db = _fake_user_deps(ADMIN_ID)
    list_response = _make_list_response()

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with (
        patch(
            "app.api.v1.corporate_expense_reports.get_user_account",
            new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID)),
        ),
        patch(
            "app.api.v1.corporate_expense_reports.list_account_expense_reports",
            new=AsyncMock(return_value=list_response),
        ),
        TestClient(app) as client,
    ):
        resp = client.get("/api/v1/corporate/accounts/me/expense-reports/all")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_api_get_expense_report():
    """31. GET /corporate/accounts/me/expense-reports/{id} → 200."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    fake_user, fake_db = _fake_user_deps(MEMBER_ID)
    report_response = _make_report_response()

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with (
        patch(
            "app.api.v1.corporate_expense_reports.get_user_account",
            new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID)),
        ),
        patch(
            "app.api.v1.corporate_expense_reports.get_expense_report",
            new=AsyncMock(return_value=report_response),
        ),
        TestClient(app) as client,
    ):
        resp = client.get(
            f"/api/v1/corporate/accounts/me/expense-reports/{REPORT_ID}"
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["id"] == REPORT_ID


@pytest.mark.asyncio
async def test_api_withdraw_expense_report():
    """32. DELETE /corporate/accounts/me/expense-reports/{id}/withdraw → 200."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    fake_user, fake_db = _fake_user_deps(MEMBER_ID)
    report_response = ExpenseReportResponse(
        id=REPORT_ID,
        account_id=ACCOUNT_ID,
        submitted_by_id=MEMBER_ID,
        ride_id=None,
        amount_usd=Decimal("75.00"),
        description="Client meeting",
        cost_center_id=None,
        trip_purpose_id=None,
        receipt_url=None,
        status="withdrawn",
        reviewed_by_id=None,
        reviewed_at=None,
        review_note=None,
        submitted_at=NOW,
        created_at=NOW,
    )

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with (
        patch(
            "app.api.v1.corporate_expense_reports.get_user_account",
            new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID)),
        ),
        patch(
            "app.api.v1.corporate_expense_reports.withdraw_expense_report",
            new=AsyncMock(return_value=report_response),
        ),
        TestClient(app) as client,
    ):
        resp = client.delete(
            f"/api/v1/corporate/accounts/me/expense-reports/{REPORT_ID}/withdraw"
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["status"] == "withdrawn"


@pytest.mark.asyncio
async def test_api_review_expense_report():
    """33. POST /corporate/accounts/me/expense-reports/{id}/review → 200."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    fake_user, fake_db = _fake_user_deps(ADMIN_ID)
    approved_response = ExpenseReportResponse(
        id=REPORT_ID,
        account_id=ACCOUNT_ID,
        submitted_by_id=MEMBER_ID,
        ride_id=None,
        amount_usd=Decimal("75.00"),
        description="Client meeting",
        cost_center_id=None,
        trip_purpose_id=None,
        receipt_url=None,
        status="approved",
        reviewed_by_id=ADMIN_ID,
        reviewed_at=NOW,
        review_note="Looks good",
        submitted_at=NOW,
        created_at=NOW,
    )

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with (
        patch(
            "app.api.v1.corporate_expense_reports.get_user_account",
            new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID)),
        ),
        patch(
            "app.api.v1.corporate_expense_reports.review_expense_report",
            new=AsyncMock(return_value=approved_response),
        ),
        TestClient(app) as client,
    ):
        resp = client.post(
            f"/api/v1/corporate/accounts/me/expense-reports/{REPORT_ID}/review",
            json={"action": "approved", "review_note": "Looks good"},
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"


@pytest.mark.asyncio
async def test_api_platform_admin_list_expense_reports():
    """34. GET /admin/corporate/accounts/{id}/expense-reports → 200."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db, require_admin

    fake_user, fake_db = _fake_user_deps(ADMIN_ID)
    list_response = _make_list_response()

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[require_admin] = lambda: fake_user

    async def fake_db_with_results():
        db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        page_result = MagicMock()
        page_result.scalars.return_value.all.return_value = []

        call_count = 0

        async def fake_execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return count_result
            return page_result

        db.execute = fake_execute
        yield db

    app.dependency_overrides[get_db] = fake_db_with_results

    with TestClient(app) as client:
        resp = client.get(
            f"/api/v1/admin/corporate/accounts/{ACCOUNT_ID}/expense-reports"
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_api_submit_no_account():
    """35. POST /expense-reports — no account → 404."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    fake_user, fake_db = _fake_user_deps(MEMBER_ID)

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with (
        patch(
            "app.api.v1.corporate_expense_reports.get_user_account",
            new=AsyncMock(return_value=None),
        ),
        TestClient(app) as client,
    ):
        resp = client.post(
            "/api/v1/corporate/accounts/me/expense-reports",
            json={"amount_usd": "50.00", "description": "Test"},
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_api_submit_ride_other_user_403():
    """36. submit with ride from other user — service 403 bubbles up."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    fake_user, fake_db = _fake_user_deps(MEMBER_ID)

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with (
        patch(
            "app.api.v1.corporate_expense_reports.get_user_account",
            new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID)),
        ),
        patch(
            "app.api.v1.corporate_expense_reports.submit_expense_report",
            new=AsyncMock(
                side_effect=HTTPException(
                    status_code=403,
                    detail="You can only expense rides you took yourself.",
                )
            ),
        ),
        TestClient(app) as client,
    ):
        resp = client.post(
            "/api/v1/corporate/accounts/me/expense-reports",
            json={"amount_usd": "50.00", "description": "X", "ride_id": RIDE_ID},
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_api_get_report_forbidden():
    """37. GET /expense-reports/{id} — forbidden → 403 passthrough."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    fake_user, fake_db = _fake_user_deps(OTHER_USER_ID)

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with (
        patch(
            "app.api.v1.corporate_expense_reports.get_user_account",
            new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID)),
        ),
        patch(
            "app.api.v1.corporate_expense_reports.get_expense_report",
            new=AsyncMock(
                side_effect=HTTPException(
                    status_code=403,
                    detail="You do not have permission to view this expense report.",
                )
            ),
        ),
        TestClient(app) as client,
    ):
        resp = client.get(
            f"/api/v1/corporate/accounts/me/expense-reports/{REPORT_ID}"
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_api_review_already_reviewed_409():
    """38. review already reviewed → 409 passthrough."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    fake_user, fake_db = _fake_user_deps(ADMIN_ID)

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with (
        patch(
            "app.api.v1.corporate_expense_reports.get_user_account",
            new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID)),
        ),
        patch(
            "app.api.v1.corporate_expense_reports.review_expense_report",
            new=AsyncMock(
                side_effect=HTTPException(
                    status_code=409,
                    detail="Only pending expense reports can be reviewed.",
                )
            ),
        ),
        TestClient(app) as client,
    ):
        resp = client.post(
            f"/api/v1/corporate/accounts/me/expense-reports/{REPORT_ID}/review",
            json={"action": "rejected"},
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_api_withdraw_non_pending_409():
    """39. withdraw non-pending → 409 passthrough."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    fake_user, fake_db = _fake_user_deps(MEMBER_ID)

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with (
        patch(
            "app.api.v1.corporate_expense_reports.get_user_account",
            new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID)),
        ),
        patch(
            "app.api.v1.corporate_expense_reports.withdraw_expense_report",
            new=AsyncMock(
                side_effect=HTTPException(
                    status_code=409,
                    detail="Only pending expense reports can be withdrawn.",
                )
            ),
        ),
        TestClient(app) as client,
    ):
        resp = client.delete(
            f"/api/v1/corporate/accounts/me/expense-reports/{REPORT_ID}/withdraw"
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_api_list_all_non_admin_403():
    """40. list_account_expense_reports non-admin → 403 passthrough."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    fake_user, fake_db = _fake_user_deps(MEMBER_ID)

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with (
        patch(
            "app.api.v1.corporate_expense_reports.get_user_account",
            new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID)),
        ),
        patch(
            "app.api.v1.corporate_expense_reports.list_account_expense_reports",
            new=AsyncMock(
                side_effect=HTTPException(
                    status_code=403,
                    detail="You do not have admin access to this corporate account.",
                )
            ),
        ),
        TestClient(app) as client,
    ):
        resp = client.get("/api/v1/corporate/accounts/me/expense-reports/all")
    app.dependency_overrides.clear()
    assert resp.status_code == 403
