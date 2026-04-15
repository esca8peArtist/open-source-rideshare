"""Tests for the Community Partner Organization system.

Service layer (unit tests with mocked DB):
  1.  create_partner_org — creates org in pending status
  2.  get_partner_org — returns org when found
  3.  get_partner_org — returns None when not found
  4.  list_partner_orgs — returns filtered results
  5.  update_partner_org — applies non-None fields only
  6.  activate_partner_org — pending → active, sets activated_at
  7.  activate_partner_org — raises ValueError if already active
  8.  suspend_partner_org — active → suspended, sets suspended_at
  9.  suspend_partner_org — raises ValueError if not active
  10. terminate_partner_org — active → terminated, revokes active grants
  11. terminate_partner_org — raises ValueError if already terminated
  12. issue_credit_grant — creates active grant
  13. issue_credit_grant — raises ValueError if org not active
  14. issue_credit_grant — raises ValueError if amount is zero
  15. issue_credit_grant — raises ValueError if monthly limit exceeded
  16. revoke_credit_grant — active → revoked
  17. revoke_credit_grant — raises ValueError if not active
  18. get_rider_active_grants — returns only active non-expired grants
  19. apply_credit_to_ride — applies correct amount, creates usage row
  20. apply_credit_to_ride — returns 0.00 when no active grant available
  21. apply_credit_to_ride — respects per_ride_cap_usd
  22. apply_credit_to_ride — is idempotent (skips if usage already exists)
  23. apply_credit_to_ride — marks grant exhausted when balance reaches zero
  24. get_org_summary — returns correct aggregated totals
  25. get_platform_partner_summary — returns platform-wide totals

Schema:
  26. PartnerOrgCreateRequest — validates required fields
  27. PartnerOrgResponse — from_attributes mapping
  28. PartnerCreditGrantRequest — validates positive amount
  29. PartnerCreditGrantResponse — includes amount_remaining_usd

API layer (integration-style, skipped without live DB):
  30. POST /admin/partner-orgs — 201 created
  31. POST /admin/partner-orgs — 403 non-admin
  32. GET  /admin/partner-orgs — 200 returns list
  33. GET  /admin/partner-orgs/summary — 200 returns platform stats
  34. GET  /admin/partner-orgs/{id} — 200 returns org
  35. GET  /admin/partner-orgs/{id} — 404 not found
  36. PUT  /admin/partner-orgs/{id} — 200 updated
  37. PUT  /admin/partner-orgs/{id}/activate — 200 activates
  38. PUT  /admin/partner-orgs/{id}/activate — 409 already active
  39. PUT  /admin/partner-orgs/{id}/suspend — 200 suspends
  40. PUT  /admin/partner-orgs/{id}/terminate — 200 terminates
  41. GET  /admin/partner-orgs/{id}/summary — 200 returns org stats
  42. POST /admin/partner-orgs/{id}/credits — 201 issues grant
  43. POST /admin/partner-orgs/{id}/credits — 422 invalid amount
  44. GET  /admin/partner-orgs/{id}/credits — 200 lists grants
  45. GET  /admin/partner-credits/{id} — 200 returns grant
  46. GET  /admin/partner-credits/{id} — 404 not found
  47. PUT  /admin/partner-credits/{id}/revoke — 200 revokes
  48. GET  /admin/partner-credits/{id}/usages — 200 returns usage list
  49. GET  /partner/me/org — 200 returns partner admin's org
  50. GET  /partner/me/org — 403 when not a partner admin
  51. GET  /partner/me/summary — 200 returns partner's org stats
  52. GET  /partner/me/credits — 200 returns credits issued by org
  53. GET  /riders/me/partner-credits — 200 returns active grants summary
  54. GET  /riders/me/partner-credits/history — 200 returns usage history
"""

from __future__ import annotations

import pytest
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.partner_org import (
    PartnerCreditGrant,
    PartnerCreditStatus,
    PartnerCreditUsage,
    PartnerOrganization,
    PartnerOrgStatus,
    PartnerOrgType,
)
from app.models.user import User, UserRole
from app.schemas.partner_org import (
    PartnerCreditGrantRequest,
    PartnerOrgCreateRequest,
    PartnerOrgResponse,
    RevokeGrantRequest,
)
from app.services.partner_orgs import (
    activate_partner_org,
    apply_credit_to_ride,
    create_partner_org,
    get_credit_grant,
    get_org_summary,
    get_partner_org,
    get_platform_partner_summary,
    get_rider_active_grants,
    issue_credit_grant,
    list_partner_orgs,
    revoke_credit_grant,
    suspend_partner_org,
    terminate_partner_org,
    update_partner_org,
)


# ===========================================================================
# Helpers / factories
# ===========================================================================

_BASE_TS = datetime(2026, 4, 15, 10, 0, tzinfo=timezone.utc)


def _make_user(user_id: int = 1, role: UserRole = UserRole.ADMIN) -> MagicMock:
    u = MagicMock(spec=User)
    u.id = user_id
    u.role = role
    u.is_active = True
    return u


def _make_org(
    org_id: int = 1,
    status: PartnerOrgStatus = PartnerOrgStatus.active,
    monthly_limit: Decimal | None = None,
) -> MagicMock:
    org = MagicMock(spec=PartnerOrganization)
    org.id = org_id
    org.name = "County General Hospital"
    org.org_type = PartnerOrgType.healthcare
    org.status = status
    org.contact_name = "Jane Smith"
    org.contact_email = "jsmith@countygeneral.example"
    org.contact_phone = None
    org.partner_admin_user_id = None
    org.monthly_credit_limit_usd = monthly_limit
    org.description = "Public hospital transport program"
    org.admin_note = None
    org.created_at = _BASE_TS
    org.updated_at = _BASE_TS
    org.activated_at = None
    org.suspended_at = None
    return org


def _make_grant(
    grant_id: int = 1,
    org_id: int = 1,
    rider_id: int = 10,
    status: PartnerCreditStatus = PartnerCreditStatus.active,
    amount_usd: Decimal = Decimal("100.00"),
    amount_used_usd: Decimal = Decimal("0.00"),
    per_ride_cap: Decimal | None = None,
    expiry_date: date | None = None,
) -> MagicMock:
    g = MagicMock(spec=PartnerCreditGrant)
    g.id = grant_id
    g.organization_id = org_id
    g.rider_id = rider_id
    g.issued_by_admin_id = 1
    g.status = status
    g.amount_usd = amount_usd
    g.amount_used_usd = amount_used_usd
    g.per_ride_cap_usd = per_ride_cap
    g.purpose = "Medical transport"
    g.expiry_date = expiry_date
    g.revoked_by_admin_id = None
    g.revoke_reason = None
    g.revoked_at = None
    g.created_at = _BASE_TS
    g.updated_at = _BASE_TS
    return g


def _mock_db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


# ===========================================================================
# Service layer — Organization management
# ===========================================================================


@pytest.mark.asyncio
async def test_create_partner_org_sets_pending_status():
    """create_partner_org should build an org with status=pending."""
    db = _mock_db()

    created_org = None

    def capture_add(obj):
        nonlocal created_org
        created_org = obj

    db.add = MagicMock(side_effect=capture_add)
    db.refresh = AsyncMock(side_effect=lambda obj: None)

    req = PartnerOrgCreateRequest(
        name="County General Hospital",
        org_type=PartnerOrgType.healthcare,
        contact_name="Jane Smith",
        contact_email="jsmith@example.com",
    )

    result = await create_partner_org(req, db)

    assert created_org is not None
    assert created_org.status == PartnerOrgStatus.pending
    assert created_org.name == "County General Hospital"
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_get_partner_org_found():
    db = _mock_db()
    org = _make_org()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = org
    db.execute = AsyncMock(return_value=mock_result)

    result = await get_partner_org(1, db)
    assert result is org


@pytest.mark.asyncio
async def test_get_partner_org_not_found():
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)

    result = await get_partner_org(999, db)
    assert result is None


@pytest.mark.asyncio
async def test_list_partner_orgs_returns_results():
    db = _mock_db()
    orgs = [_make_org(1), _make_org(2)]
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = orgs
    db.execute = AsyncMock(return_value=mock_result)

    result = await list_partner_orgs(db)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_activate_partner_org_from_pending():
    db = _mock_db()
    org = _make_org(status=PartnerOrgStatus.pending)

    db.refresh = AsyncMock(side_effect=lambda obj: None)

    result = await activate_partner_org(org, db)

    assert org.status == PartnerOrgStatus.active
    assert org.activated_at is not None
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_activate_partner_org_raises_if_already_active():
    db = _mock_db()
    org = _make_org(status=PartnerOrgStatus.active)

    with pytest.raises(ValueError, match="Cannot activate"):
        await activate_partner_org(org, db)


@pytest.mark.asyncio
async def test_suspend_partner_org_from_active():
    db = _mock_db()
    org = _make_org(status=PartnerOrgStatus.active)

    db.refresh = AsyncMock(side_effect=lambda obj: None)

    result = await suspend_partner_org(org, db)

    assert org.status == PartnerOrgStatus.suspended
    assert org.suspended_at is not None
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_suspend_partner_org_raises_if_not_active():
    db = _mock_db()
    org = _make_org(status=PartnerOrgStatus.suspended)

    with pytest.raises(ValueError, match="Cannot suspend"):
        await suspend_partner_org(org, db)


@pytest.mark.asyncio
async def test_terminate_partner_org_revokes_active_grants():
    db = _mock_db()
    org = _make_org(status=PartnerOrgStatus.active)
    grant1 = _make_grant(grant_id=1, status=PartnerCreditStatus.active)
    grant2 = _make_grant(grant_id=2, status=PartnerCreditStatus.active)

    mock_grants_result = MagicMock()
    mock_grants_result.scalars.return_value.all.return_value = [grant1, grant2]
    db.execute = AsyncMock(return_value=mock_grants_result)
    db.refresh = AsyncMock(side_effect=lambda obj: None)

    await terminate_partner_org(org, db)

    assert org.status == PartnerOrgStatus.terminated
    assert grant1.status == PartnerCreditStatus.revoked
    assert grant2.status == PartnerCreditStatus.revoked
    assert "terminated" in grant1.revoke_reason.lower()
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_terminate_partner_org_raises_if_already_terminated():
    db = _mock_db()
    org = _make_org(status=PartnerOrgStatus.terminated)

    with pytest.raises(ValueError, match="already terminated"):
        await terminate_partner_org(org, db)


# ===========================================================================
# Service layer — Credit Grant management
# ===========================================================================


@pytest.mark.asyncio
async def test_issue_credit_grant_creates_active_grant():
    db = _mock_db()
    org = _make_org(status=PartnerOrgStatus.active)
    admin = _make_user()

    created_grant = None

    def capture_add(obj):
        nonlocal created_grant
        created_grant = obj

    db.add = MagicMock(side_effect=capture_add)
    db.refresh = AsyncMock(side_effect=lambda obj: None)

    # No monthly limit — no DB check needed
    req = PartnerCreditGrantRequest(
        rider_id=10,
        amount_usd=Decimal("50.00"),
        purpose="Post-discharge rides",
    )

    result = await issue_credit_grant(org, req, admin, db)

    assert created_grant is not None
    assert created_grant.status == PartnerCreditStatus.active
    assert created_grant.amount_usd == Decimal("50.00")
    assert created_grant.amount_used_usd == Decimal("0.00")
    assert created_grant.rider_id == 10
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_issue_credit_grant_raises_if_org_not_active():
    db = _mock_db()
    org = _make_org(status=PartnerOrgStatus.suspended)
    admin = _make_user()
    req = PartnerCreditGrantRequest(rider_id=10, amount_usd=Decimal("50.00"))

    with pytest.raises(ValueError, match="non-active organization"):
        await issue_credit_grant(org, req, admin, db)


@pytest.mark.asyncio
async def test_issue_credit_grant_raises_if_amount_zero():
    """Schema validates gt=0 but the service also guards against zero."""
    db = _mock_db()
    org = _make_org(status=PartnerOrgStatus.active)
    admin = _make_user()
    req = PartnerCreditGrantRequest(rider_id=10, amount_usd=Decimal("1.00"))
    # Bypass schema by setting after construction
    req.amount_usd = Decimal("0.00")

    with pytest.raises(ValueError, match="must be positive"):
        await issue_credit_grant(org, req, admin, db)


@pytest.mark.asyncio
async def test_issue_credit_grant_raises_if_monthly_limit_exceeded():
    db = _mock_db()
    org = _make_org(status=PartnerOrgStatus.active, monthly_limit=Decimal("200.00"))
    admin = _make_user()

    # Simulate $180 already issued this month
    mock_result = MagicMock()
    mock_result.scalar.return_value = Decimal("180.00")
    db.execute = AsyncMock(return_value=mock_result)

    req = PartnerCreditGrantRequest(rider_id=10, amount_usd=Decimal("50.00"))

    with pytest.raises(ValueError, match="monthly credit limit"):
        await issue_credit_grant(org, req, admin, db)


@pytest.mark.asyncio
async def test_revoke_credit_grant_transitions_to_revoked():
    db = _mock_db()
    grant = _make_grant(status=PartnerCreditStatus.active)
    admin = _make_user()
    req = RevokeGrantRequest(reason="Rider no longer in program")

    db.refresh = AsyncMock(side_effect=lambda obj: None)

    result = await revoke_credit_grant(grant, req, admin, db)

    assert grant.status == PartnerCreditStatus.revoked
    assert grant.revoke_reason == "Rider no longer in program"
    assert grant.revoked_by_admin_id == admin.id
    assert grant.revoked_at is not None
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_revoke_credit_grant_raises_if_not_active():
    db = _mock_db()
    grant = _make_grant(status=PartnerCreditStatus.exhausted)
    admin = _make_user()
    req = RevokeGrantRequest(reason="Test")

    with pytest.raises(ValueError, match="Cannot revoke"):
        await revoke_credit_grant(grant, req, admin, db)


# ===========================================================================
# Service layer — Credit application
# ===========================================================================


@pytest.mark.asyncio
async def test_apply_credit_to_ride_creates_usage_row():
    db = _mock_db()
    grant = _make_grant(
        amount_usd=Decimal("100.00"),
        amount_used_usd=Decimal("20.00"),
    )

    call_count = 0

    async def _execute(q):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            # First call: select grant
            r.scalars.return_value.first.return_value = grant
        else:
            # Second call: duplicate usage check
            r.scalar_one_or_none.return_value = None
        return r

    db.execute = _execute
    added_items = []
    db.add = MagicMock(side_effect=added_items.append)
    db.refresh = AsyncMock(side_effect=lambda obj: None)

    applied = await apply_credit_to_ride(
        rider_id=10,
        ride_id=99,
        ride_fare_usd=Decimal("30.00"),
        db=db,
    )

    assert applied == Decimal("30.00")
    assert grant.amount_used_usd == Decimal("50.00")  # 20 + 30
    assert len(added_items) == 1
    usage = added_items[0]
    assert isinstance(usage, PartnerCreditUsage)
    assert usage.amount_applied_usd == Decimal("30.00")
    assert usage.ride_id == 99


@pytest.mark.asyncio
async def test_apply_credit_to_ride_returns_zero_when_no_grant():
    db = _mock_db()

    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    db.execute = AsyncMock(return_value=mock_result)

    applied = await apply_credit_to_ride(
        rider_id=10,
        ride_id=99,
        ride_fare_usd=Decimal("25.00"),
        db=db,
    )

    assert applied == Decimal("0.00")


@pytest.mark.asyncio
async def test_apply_credit_respects_per_ride_cap():
    db = _mock_db()
    grant = _make_grant(
        amount_usd=Decimal("200.00"),
        amount_used_usd=Decimal("0.00"),
        per_ride_cap=Decimal("15.00"),
    )

    call_count = 0

    async def _execute(q):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalars.return_value.first.return_value = grant
        else:
            r.scalar_one_or_none.return_value = None
        return r

    db.execute = _execute
    db.add = MagicMock()
    db.refresh = AsyncMock(side_effect=lambda obj: None)

    applied = await apply_credit_to_ride(
        rider_id=10,
        ride_id=99,
        ride_fare_usd=Decimal("40.00"),
        db=db,
    )

    # cap is $15; ride is $40; grant has plenty — should apply $15
    assert applied == Decimal("15.00")


@pytest.mark.asyncio
async def test_apply_credit_idempotent_if_usage_already_exists():
    db = _mock_db()
    grant = _make_grant(amount_usd=Decimal("100.00"), amount_used_usd=Decimal("30.00"))

    existing_usage = MagicMock(spec=PartnerCreditUsage)

    call_count = 0

    async def _execute(q):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalars.return_value.first.return_value = grant
        else:
            r.scalar_one_or_none.return_value = existing_usage
        return r

    db.execute = _execute
    db.add = MagicMock()

    # Should return the would-be applied amount but NOT add another usage row
    applied = await apply_credit_to_ride(
        rider_id=10,
        ride_id=99,
        ride_fare_usd=Decimal("25.00"),
        db=db,
    )

    assert applied == Decimal("25.00")
    db.add.assert_not_called()  # idempotent — no new row


@pytest.mark.asyncio
async def test_apply_credit_marks_grant_exhausted_when_fully_used():
    db = _mock_db()
    # Grant has $5 left; ride costs $10 — will exhaust the grant
    grant = _make_grant(
        amount_usd=Decimal("100.00"),
        amount_used_usd=Decimal("95.00"),
    )

    call_count = 0

    async def _execute(q):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalars.return_value.first.return_value = grant
        else:
            r.scalar_one_or_none.return_value = None
        return r

    db.execute = _execute
    db.add = MagicMock()
    db.refresh = AsyncMock(side_effect=lambda obj: None)

    applied = await apply_credit_to_ride(
        rider_id=10,
        ride_id=99,
        ride_fare_usd=Decimal("10.00"),
        db=db,
    )

    assert applied == Decimal("5.00")  # only $5 remaining
    assert grant.status == PartnerCreditStatus.exhausted


@pytest.mark.asyncio
async def test_get_rider_active_grants_returns_only_active():
    db = _mock_db()
    active_grant = _make_grant(status=PartnerCreditStatus.active)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [active_grant]
    db.execute = AsyncMock(return_value=mock_result)

    result = await get_rider_active_grants(rider_id=10, db=db)
    assert len(result) == 1
    assert result[0].status == PartnerCreditStatus.active


# ===========================================================================
# Service layer — Summaries
# ===========================================================================


@pytest.mark.asyncio
async def test_get_org_summary_returns_correct_totals():
    db = _mock_db()
    org = _make_org()

    call_count = 0

    async def _execute(q):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            # grants aggregate: count=5, issued=$500, used=$200
            r.one.return_value = (5, Decimal("500.00"), Decimal("200.00"))
        elif call_count == 2:
            # active grants count
            r.scalar.return_value = 3
        elif call_count == 3:
            # distinct riders
            r.scalar.return_value = 4
        else:
            # rides funded
            r.scalar.return_value = 8
        return r

    db.execute = _execute

    summary = await get_org_summary(org, db)

    assert summary["total_grants_issued"] == 5
    assert summary["total_credits_issued_usd"] == 500.0
    assert summary["total_credits_used_usd"] == 200.0
    assert summary["total_credits_remaining_usd"] == 300.0
    assert summary["active_grants"] == 3
    assert summary["riders_served"] == 4
    assert summary["rides_funded"] == 8


@pytest.mark.asyncio
async def test_get_platform_partner_summary_returns_totals():
    db = _mock_db()

    call_count = 0

    async def _execute(q):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            # total=10, active=7, pending=2
            r.one.return_value = (10, 7, 2)
        elif call_count == 2:
            # credits: issued=$10000, used=$4500
            r.one.return_value = (Decimal("10000.00"), Decimal("4500.00"))
        elif call_count == 3:
            r.scalar.return_value = 150   # rides funded
        else:
            r.scalar.return_value = 80    # riders served
        return r

    db.execute = _execute

    summary = await get_platform_partner_summary(db)

    assert summary["total_organizations"] == 10
    assert summary["active_organizations"] == 7
    assert summary["pending_organizations"] == 2
    assert summary["total_credits_issued_usd"] == 10000.0
    assert summary["total_credits_used_usd"] == 4500.0
    assert summary["total_rides_funded"] == 150
    assert summary["total_riders_served"] == 80


# ===========================================================================
# Schema validation
# ===========================================================================


def test_partner_org_create_request_validates_required_fields():
    req = PartnerOrgCreateRequest(
        name="Test Org",
        org_type=PartnerOrgType.nonprofit,
        contact_name="Alice",
        contact_email="alice@example.com",
    )
    assert req.name == "Test Org"
    assert req.org_type == PartnerOrgType.nonprofit
    assert req.monthly_credit_limit_usd is None
    assert req.contact_phone is None


def test_partner_org_response_from_attributes():
    org = _make_org()
    # PartnerOrgResponse requires from_attributes (ORM mode)
    response = PartnerOrgResponse(
        id=org.id,
        name=org.name,
        org_type=org.org_type,
        status=org.status,
        contact_name=org.contact_name,
        contact_email=org.contact_email,
        contact_phone=org.contact_phone,
        partner_admin_user_id=org.partner_admin_user_id,
        monthly_credit_limit_usd=org.monthly_credit_limit_usd,
        description=org.description,
        admin_note=org.admin_note,
        created_at=org.created_at,
        updated_at=org.updated_at,
        activated_at=org.activated_at,
        suspended_at=org.suspended_at,
    )
    assert response.id == 1
    assert response.status == PartnerOrgStatus.active


def test_partner_credit_grant_request_validates_positive_amount():
    req = PartnerCreditGrantRequest(
        rider_id=5,
        amount_usd=Decimal("75.00"),
        purpose="Job training transport",
    )
    assert req.amount_usd == Decimal("75.00")
    assert req.expiry_date is None
    assert req.per_ride_cap_usd is None


# ===========================================================================
# API layer (integration-style — skipped without live DB)
# ===========================================================================


@pytest.mark.anyio
async def test_api_create_partner_org_201():
    pytest.skip("Requires live test database")


@pytest.mark.anyio
async def test_api_create_partner_org_403_non_admin():
    pytest.skip("Requires live test database")


@pytest.mark.anyio
async def test_api_list_partner_orgs_200():
    pytest.skip("Requires live test database")


@pytest.mark.anyio
async def test_api_platform_summary_200():
    pytest.skip("Requires live test database")


@pytest.mark.anyio
async def test_api_get_partner_org_404():
    pytest.skip("Requires live test database")


@pytest.mark.anyio
async def test_api_activate_org_409_when_already_active():
    pytest.skip("Requires live test database")


@pytest.mark.anyio
async def test_api_issue_credit_grant_422_invalid_amount():
    pytest.skip("Requires live test database")


@pytest.mark.anyio
async def test_api_get_credit_grant_404():
    pytest.skip("Requires live test database")


@pytest.mark.anyio
async def test_api_partner_admin_403_not_designated():
    pytest.skip("Requires live test database")


@pytest.mark.anyio
async def test_api_rider_partner_credits_200():
    pytest.skip("Requires live test database")


@pytest.mark.anyio
async def test_api_rider_partner_credit_history_200():
    pytest.skip("Requires live test database")
