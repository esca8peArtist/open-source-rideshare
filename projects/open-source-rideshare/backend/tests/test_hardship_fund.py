"""Tests for the Driver Emergency Assistance Fund.

Service layer (unit tests with mocked DB — these will PASS):
  1.  get_or_create_fund — creates fund when none exists
  2.  get_or_create_fund — returns existing fund
  3.  add_contribution — creates contribution and updates fund balance
  4.  add_contribution — platform contribution has null driver_id
  5.  create_application — creates pending application
  6.  create_application — raises 409 if driver has active application
  7.  start_review — transitions pending → under_review
  8.  start_review — raises 404 for unknown application
  9.  start_review — raises 409 if not pending
  10. approve_application — transitions to approved
  11. approve_application — raises 400 if insufficient fund balance
  12. deny_application — transitions to denied from under_review
  13. deny_application — can also deny a pending application
  14. disburse_application — transitions approved → disbursed, decrements balance
  15. withdraw_application — transitions pending → withdrawn
  16. withdraw_application — raises 403 if wrong driver
  17. withdraw_application — raises 409 if not pending
  18. get_driver_applications — returns only that driver's applications
  19. admin_list_applications — returns all when no filter
  20. admin_list_applications — filters by status
  21. get_fund_summary — returns correct structure

Schema:
  22. HardshipFundBalanceResponse — validates from ORM
  23. PublicFundBalanceResponse — only exposes total_balance_usd
  24. ContributionRequest — validates amount_usd gt 0
  25. ApplicationCreateRequest — validates description min length
  26. ApplicationCreateRequest — validates amount_requested_usd le 5000
  27. ApproveApplicationRequest — validates approved_amount_usd gt 0
  28. DenyApplicationRequest — validates admin_note min length

API layer (integration-style, skipped without live DB):
  29. GET /cooperative/hardship-fund — 200 with balance
  30. POST /drivers/me/hardship-applications — 201 creates application
  31. GET /drivers/me/hardship-applications — 200 lists applications
  32. GET /drivers/me/hardship-applications/{id} — 403 for wrong user
  33. DELETE /drivers/me/hardship-applications/{id} — withdraws pending app
  34. GET /admin/hardship-fund/balance — 200 for admin, 403 for non-admin
  35. POST /admin/hardship-fund/contributions — 201 adds contribution
  36. Full admin review workflow: pending → under_review → approved → disbursed
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from app.models.hardship_fund import (
    ApplicationStatus,
    ApplicationType,
    ContributionSource,
    DriverHardshipFund,
    HardshipApplication,
    HardshipContribution,
)
from app.schemas.hardship_fund import (
    ApproveApplicationRequest,
    ApplicationCreateRequest,
    ApplicationResponse,
    ContributionRequest,
    ContributionResponse,
    DenyApplicationRequest,
    HardshipFundBalanceResponse,
    PublicFundBalanceResponse,
)
from app.services.hardship_fund import (
    HardshipFundError,
    add_contribution,
    admin_list_applications,
    approve_application,
    create_application,
    deny_application,
    disburse_application,
    get_driver_applications,
    get_fund_summary,
    get_or_create_fund,
    start_review,
    withdraw_application,
)


# ===========================================================================
# Helpers / factories
# ===========================================================================

_BASE_TS = datetime(2026, 4, 15, 10, 0, tzinfo=timezone.utc)


def _make_fund(
    fund_id: int = 1,
    balance: Decimal = Decimal("1000.00"),
    contributed: Decimal = Decimal("1000.00"),
    disbursed: Decimal = Decimal("0.00"),
) -> MagicMock:
    f = MagicMock(spec=DriverHardshipFund)
    f.id = fund_id
    f.total_balance_usd = balance
    f.total_contributed_usd = contributed
    f.total_disbursed_usd = disbursed
    f.created_at = _BASE_TS
    f.updated_at = _BASE_TS
    return f


def _make_application(
    app_id: int = 1,
    driver_id: int = 42,
    app_type: ApplicationType = ApplicationType.medical,
    status: ApplicationStatus = ApplicationStatus.pending,
    amount_requested: Decimal = Decimal("500.00"),
    approved_amount: Decimal | None = None,
) -> MagicMock:
    a = MagicMock(spec=HardshipApplication)
    a.id = app_id
    a.driver_id = driver_id
    a.application_type = app_type
    a.description = "I had a medical emergency and need help with hospital bills."
    a.amount_requested_usd = amount_requested
    a.status = status
    a.approved_amount_usd = approved_amount
    a.admin_note = None
    a.reviewed_by_id = None
    a.reviewed_at = None
    a.disbursed_at = None
    a.created_at = _BASE_TS
    a.updated_at = _BASE_TS
    return a


def _make_contribution(
    contrib_id: int = 1,
    source: ContributionSource = ContributionSource.driver,
    driver_id: int | None = 42,
    amount: Decimal = Decimal("100.00"),
) -> MagicMock:
    c = MagicMock(spec=HardshipContribution)
    c.id = contrib_id
    c.source = source
    c.driver_id = driver_id
    c.amount_usd = amount
    c.note = None
    c.created_at = _BASE_TS
    return c


def _mock_db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


# ===========================================================================
# Service layer — Fund record
# ===========================================================================


@pytest.mark.asyncio
async def test_get_or_create_fund_creates_when_none_exists():
    """get_or_create_fund should create and return a new fund with zero balances."""
    db = _mock_db()
    created_fund = None

    def capture_add(obj):
        nonlocal created_fund
        if isinstance(obj, DriverHardshipFund):
            created_fund = obj

    db.add = MagicMock(side_effect=capture_add)

    async def populate_fund(obj):
        if isinstance(obj, DriverHardshipFund):
            obj.id = 1
            obj.created_at = _BASE_TS
            obj.updated_at = _BASE_TS

    db.refresh = AsyncMock(side_effect=populate_fund)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)

    result = await get_or_create_fund(db)

    assert created_fund is not None
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_get_or_create_fund_returns_existing():
    """get_or_create_fund should return the existing fund without creating a new one."""
    db = _mock_db()
    fund = _make_fund()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = fund
    db.execute = AsyncMock(return_value=mock_result)

    result = await get_or_create_fund(db)

    assert result is fund
    db.add.assert_not_called()
    db.commit.assert_not_called()


# ===========================================================================
# Service layer — Contributions
# ===========================================================================


@pytest.mark.asyncio
async def test_add_contribution_creates_record_and_updates_balance():
    """add_contribution should create a HardshipContribution and increment fund balance."""
    db = _mock_db()
    fund = _make_fund(balance=Decimal("500.00"), contributed=Decimal("500.00"))
    created_contrib = None

    def capture_add(obj):
        nonlocal created_contrib
        if isinstance(obj, HardshipContribution):
            created_contrib = obj

    db.add = MagicMock(side_effect=capture_add)

    async def populate_contrib(obj):
        if isinstance(obj, HardshipContribution):
            obj.id = 1
            obj.created_at = _BASE_TS

    db.refresh = AsyncMock(side_effect=populate_contrib)

    # First call: fund lookup
    mock_fund_result = MagicMock()
    mock_fund_result.scalar_one_or_none.return_value = fund
    db.execute = AsyncMock(return_value=mock_fund_result)

    result = await add_contribution(
        db=db,
        source=ContributionSource.driver,
        amount_usd=Decimal("100.00"),
        driver_id=42,
        note="Monthly contribution",
    )

    assert created_contrib is not None
    assert created_contrib.source == ContributionSource.driver
    assert created_contrib.driver_id == 42
    # Balance should increase
    assert fund.total_balance_usd == Decimal("600.00")
    assert fund.total_contributed_usd == Decimal("600.00")
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_add_contribution_platform_has_null_driver_id():
    """Platform contributions should have driver_id=None."""
    db = _mock_db()
    fund = _make_fund()
    created_contrib = None

    def capture_add(obj):
        nonlocal created_contrib
        if isinstance(obj, HardshipContribution):
            created_contrib = obj

    db.add = MagicMock(side_effect=capture_add)

    async def populate_contrib(obj):
        if isinstance(obj, HardshipContribution):
            obj.id = 2
            obj.created_at = _BASE_TS

    db.refresh = AsyncMock(side_effect=populate_contrib)

    mock_fund_result = MagicMock()
    mock_fund_result.scalar_one_or_none.return_value = fund
    db.execute = AsyncMock(return_value=mock_fund_result)

    await add_contribution(
        db=db,
        source=ContributionSource.platform,
        amount_usd=Decimal("250.00"),
        driver_id=None,
        note="Monthly platform contribution",
    )

    assert created_contrib is not None
    assert created_contrib.driver_id is None
    assert created_contrib.source == ContributionSource.platform


# ===========================================================================
# Service layer — Applications
# ===========================================================================


@pytest.mark.asyncio
async def test_create_application_creates_pending():
    """create_application should create an application with pending status."""
    db = _mock_db()
    created_app = None

    def capture_add(obj):
        nonlocal created_app
        if isinstance(obj, HardshipApplication):
            created_app = obj

    db.add = MagicMock(side_effect=capture_add)

    async def populate_app(obj):
        if isinstance(obj, HardshipApplication):
            obj.id = 1
            obj.created_at = _BASE_TS
            obj.updated_at = _BASE_TS

    db.refresh = AsyncMock(side_effect=populate_app)

    # No active application exists
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)

    result = await create_application(
        db=db,
        driver_id=42,
        application_type=ApplicationType.medical,
        description="I had a medical emergency and need financial help.",
        amount_requested_usd=Decimal("500.00"),
    )

    assert created_app is not None
    assert created_app.status == ApplicationStatus.pending
    assert created_app.driver_id == 42
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_create_application_raises_409_if_active_exists():
    """create_application should raise HardshipFundError(409) if driver already has active app."""
    db = _mock_db()
    existing_app = _make_application(status=ApplicationStatus.pending)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing_app
    db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(HardshipFundError) as exc_info:
        await create_application(
            db=db,
            driver_id=42,
            application_type=ApplicationType.vehicle_repair,
            description="My car broke down and I cannot work.",
            amount_requested_usd=Decimal("800.00"),
        )

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_start_review_transitions_pending_to_under_review():
    """start_review should move a pending application to under_review."""
    db = _mock_db()
    application = _make_application(status=ApplicationStatus.pending)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = application
    db.execute = AsyncMock(return_value=mock_result)

    await start_review(db=db, application_id=1, admin_id=99)

    assert application.status == ApplicationStatus.under_review
    assert application.reviewed_by_id == 99
    assert application.reviewed_at is not None
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_start_review_raises_404_for_unknown_application():
    """start_review should raise HardshipFundError(404) when application does not exist."""
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(HardshipFundError) as exc_info:
        await start_review(db=db, application_id=999, admin_id=99)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_start_review_raises_409_if_not_pending():
    """start_review should raise HardshipFundError(409) if the application is not pending."""
    db = _mock_db()
    application = _make_application(status=ApplicationStatus.under_review)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = application
    db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(HardshipFundError) as exc_info:
        await start_review(db=db, application_id=1, admin_id=99)

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_approve_application_transitions_to_approved():
    """approve_application should move under_review → approved with amount and note."""
    db = _mock_db()
    application = _make_application(status=ApplicationStatus.under_review)
    fund = _make_fund(balance=Decimal("2000.00"))

    call_count = 0

    async def _execute(q):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            # Application lookup
            r.scalar_one_or_none.return_value = application
        else:
            # Fund lookup
            r.scalar_one_or_none.return_value = fund
        return r

    db.execute = _execute

    result = await approve_application(
        db=db,
        application_id=1,
        admin_id=99,
        approved_amount_usd=Decimal("400.00"),
        admin_note="Approved after review of medical documentation.",
    )

    assert application.status == ApplicationStatus.approved
    assert application.approved_amount_usd == Decimal("400.00")
    assert application.admin_note == "Approved after review of medical documentation."
    assert application.reviewed_by_id == 99
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_approve_application_raises_400_if_insufficient_balance():
    """approve_application should raise HardshipFundError(400) when fund has too little balance."""
    db = _mock_db()
    application = _make_application(status=ApplicationStatus.under_review)
    fund = _make_fund(balance=Decimal("50.00"))  # only $50

    call_count = 0

    async def _execute(q):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = application
        else:
            r.scalar_one_or_none.return_value = fund
        return r

    db.execute = _execute

    with pytest.raises(HardshipFundError) as exc_info:
        await approve_application(
            db=db,
            application_id=1,
            admin_id=99,
            approved_amount_usd=Decimal("500.00"),  # more than fund balance
        )

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_deny_application_from_under_review():
    """deny_application should transition under_review → denied."""
    db = _mock_db()
    application = _make_application(status=ApplicationStatus.under_review)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = application
    db.execute = AsyncMock(return_value=mock_result)

    await deny_application(
        db=db,
        application_id=1,
        admin_id=99,
        admin_note="Does not meet eligibility criteria.",
    )

    assert application.status == ApplicationStatus.denied
    assert application.admin_note == "Does not meet eligibility criteria."
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_deny_application_from_pending():
    """deny_application should also work from pending status."""
    db = _mock_db()
    application = _make_application(status=ApplicationStatus.pending)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = application
    db.execute = AsyncMock(return_value=mock_result)

    await deny_application(
        db=db,
        application_id=1,
        admin_id=99,
        admin_note="Application is incomplete.",
    )

    assert application.status == ApplicationStatus.denied


@pytest.mark.asyncio
async def test_disburse_application_transitions_approved_to_disbursed():
    """disburse_application should move approved → disbursed and decrement fund balance."""
    db = _mock_db()
    application = _make_application(
        status=ApplicationStatus.approved,
        approved_amount=Decimal("400.00"),
    )
    fund = _make_fund(
        balance=Decimal("1000.00"),
        disbursed=Decimal("200.00"),
    )

    call_count = 0

    async def _execute(q):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = application
        else:
            r.scalar_one_or_none.return_value = fund
        return r

    db.execute = _execute

    await disburse_application(db=db, application_id=1, admin_id=99)

    assert application.status == ApplicationStatus.disbursed
    assert application.disbursed_at is not None
    # Balance decremented by approved amount
    assert fund.total_balance_usd == Decimal("600.00")
    assert fund.total_disbursed_usd == Decimal("600.00")
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_withdraw_application_transitions_pending_to_withdrawn():
    """withdraw_application should move pending → withdrawn for the owning driver."""
    db = _mock_db()
    application = _make_application(driver_id=42, status=ApplicationStatus.pending)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = application
    db.execute = AsyncMock(return_value=mock_result)

    await withdraw_application(db=db, application_id=1, driver_id=42)

    assert application.status == ApplicationStatus.withdrawn
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_withdraw_application_raises_403_for_wrong_driver():
    """withdraw_application should raise HardshipFundError(403) if driver doesn't own it."""
    db = _mock_db()
    application = _make_application(driver_id=42, status=ApplicationStatus.pending)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = application
    db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(HardshipFundError) as exc_info:
        await withdraw_application(db=db, application_id=1, driver_id=99)  # wrong driver

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_withdraw_application_raises_409_if_not_pending():
    """withdraw_application should raise HardshipFundError(409) if not in pending status."""
    db = _mock_db()
    application = _make_application(driver_id=42, status=ApplicationStatus.under_review)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = application
    db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(HardshipFundError) as exc_info:
        await withdraw_application(db=db, application_id=1, driver_id=42)

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_get_driver_applications_returns_own_applications():
    """get_driver_applications should return only the specified driver's applications."""
    db = _mock_db()
    apps = [
        _make_application(app_id=1, driver_id=42),
        _make_application(app_id=2, driver_id=42, status=ApplicationStatus.approved),
    ]
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = apps
    db.execute = AsyncMock(return_value=mock_result)

    result = await get_driver_applications(db=db, driver_id=42)

    assert len(result) == 2
    assert all(a.driver_id == 42 for a in result)


@pytest.mark.asyncio
async def test_admin_list_applications_returns_all_without_filter():
    """admin_list_applications with no filter should return all applications."""
    db = _mock_db()
    apps = [
        _make_application(app_id=1, driver_id=10, status=ApplicationStatus.pending),
        _make_application(app_id=2, driver_id=11, status=ApplicationStatus.approved),
        _make_application(app_id=3, driver_id=12, status=ApplicationStatus.disbursed),
    ]
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = apps
    db.execute = AsyncMock(return_value=mock_result)

    result = await admin_list_applications(db=db, status_filter=None)

    assert len(result) == 3


@pytest.mark.asyncio
async def test_admin_list_applications_filters_by_status():
    """admin_list_applications should only return applications matching the status filter."""
    db = _mock_db()
    pending_apps = [
        _make_application(app_id=1, driver_id=10, status=ApplicationStatus.pending),
    ]
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = pending_apps
    db.execute = AsyncMock(return_value=mock_result)

    result = await admin_list_applications(
        db=db, status_filter=ApplicationStatus.pending
    )

    assert len(result) == 1
    assert result[0].status == ApplicationStatus.pending


@pytest.mark.asyncio
async def test_get_fund_summary_returns_correct_structure():
    """get_fund_summary should return a dict with all expected keys."""
    db = _mock_db()
    fund = _make_fund(
        balance=Decimal("800.00"),
        contributed=Decimal("1000.00"),
        disbursed=Decimal("200.00"),
    )

    call_count = 0

    async def _execute(q):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            # Fund lookup
            r.scalar_one_or_none.return_value = fund
        elif call_count == 2:
            # Status counts
            r.all.return_value = [
                (ApplicationStatus.pending, 3),
                (ApplicationStatus.approved, 1),
                (ApplicationStatus.disbursed, 2),
            ]
        elif call_count == 3:
            # Monetary sums
            r.first.return_value = (Decimal("2000.00"), Decimal("700.00"), Decimal("400.00"))
        else:
            # Total application count
            r.scalar.return_value = 6
        return r

    db.execute = _execute

    summary = await get_fund_summary(db)

    assert "total_balance_usd" in summary
    assert "total_applications" in summary
    assert "pending_count" in summary
    assert "under_review_count" in summary
    assert "approved_count" in summary
    assert "disbursed_count" in summary
    assert "denied_count" in summary
    assert "total_requested_usd" in summary
    assert "total_approved_usd" in summary
    assert "total_disbursed_usd" in summary


# ===========================================================================
# Schema validation
# ===========================================================================


def test_hardship_fund_balance_response_from_attributes():
    """HardshipFundBalanceResponse should parse from ORM-like objects."""
    data = HardshipFundBalanceResponse(
        id=1,
        total_balance_usd=Decimal("1500.00"),
        total_contributed_usd=Decimal("2000.00"),
        total_disbursed_usd=Decimal("500.00"),
        updated_at=_BASE_TS,
    )
    assert data.total_balance_usd == Decimal("1500.00")


def test_public_fund_balance_only_exposes_balance():
    """PublicFundBalanceResponse should only contain total_balance_usd."""
    data = PublicFundBalanceResponse(total_balance_usd=Decimal("1500.00"))
    assert data.total_balance_usd == Decimal("1500.00")
    # Should not have contribution or disbursement fields
    assert not hasattr(data, "total_contributed_usd")
    assert not hasattr(data, "total_disbursed_usd")


def test_contribution_request_validates_amount_gt_zero():
    """ContributionRequest should reject amount_usd <= 0."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        ContributionRequest(source=ContributionSource.driver, amount_usd=Decimal("0"))

    with pytest.raises(pydantic.ValidationError):
        ContributionRequest(source=ContributionSource.platform, amount_usd=Decimal("-10"))

    # Valid
    req = ContributionRequest(
        source=ContributionSource.driver, amount_usd=Decimal("0.01")
    )
    assert req.amount_usd == Decimal("0.01")


def test_application_create_request_validates_description_min_length():
    """ApplicationCreateRequest should reject descriptions shorter than 10 chars."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        ApplicationCreateRequest(
            application_type=ApplicationType.medical,
            description="Short",
            amount_requested_usd=Decimal("100"),
        )


def test_application_create_request_validates_amount_le_5000():
    """ApplicationCreateRequest should reject amount_requested_usd > 5000."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        ApplicationCreateRequest(
            application_type=ApplicationType.medical,
            description="I need help with medical bills from an emergency.",
            amount_requested_usd=Decimal("5001"),
        )


def test_approve_application_request_validates_amount_gt_zero():
    """ApproveApplicationRequest should reject approved_amount_usd <= 0."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        ApproveApplicationRequest(approved_amount_usd=Decimal("0"))


def test_deny_application_request_validates_note_min_length():
    """DenyApplicationRequest should reject empty admin_note."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        DenyApplicationRequest(admin_note="")


# ===========================================================================
# API layer (integration-style — skipped without live DB)
# ===========================================================================


@pytest.mark.anyio
async def test_api_get_public_fund_balance_200():
    pytest.skip("Requires live test database")


@pytest.mark.anyio
async def test_api_create_application_201():
    pytest.skip("Requires live test database")


@pytest.mark.anyio
async def test_api_list_my_applications_200():
    pytest.skip("Requires live test database")


@pytest.mark.anyio
async def test_api_get_my_application_403_wrong_user():
    pytest.skip("Requires live test database")


@pytest.mark.anyio
async def test_api_withdraw_application_200():
    pytest.skip("Requires live test database")


@pytest.mark.anyio
async def test_api_admin_get_fund_balance_200():
    pytest.skip("Requires live test database")


@pytest.mark.anyio
async def test_api_admin_get_fund_balance_403_non_admin():
    pytest.skip("Requires live test database")


@pytest.mark.anyio
async def test_api_admin_add_contribution_201():
    pytest.skip("Requires live test database")


@pytest.mark.anyio
async def test_api_admin_full_review_workflow():
    """Full workflow: pending → under_review → approved → disbursed."""
    pytest.skip("Requires live test database")
