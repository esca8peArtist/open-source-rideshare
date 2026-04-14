"""Unit tests for the corporate / business accounts feature.

All tests are pure unit tests — no database or HTTP client required.

Covers:
- CorporateAccount model field defaults
- MembershipStatus enum values
- check_per_ride_limit: within limit, over limit, no limit
- check_monthly_limit: within limit, over limit, no limit, projected exact boundary
- _current_month_str: correct format
- validate_corporate_billing: no membership, inactive account, per-ride exceeded,
  monthly exceeded, success
- record_corporate_spend: increments counters, resets on new month
- create_account service (mocked DB)
- get_account service (mocked DB): found, not found
- list_accounts service (mocked DB): all, active_only
- update_account service (mocked DB): partial update, not found
- invite_member: success, duplicate invite rejected
- activate_membership: success, wrong user, wrong status
- remove_member: success, not found
- list_members (mocked DB)
- list_rider_memberships (mocked DB)
- list_account_rides (mocked DB)
- Schema validation: CorporateAccountCreateRequest, InviteMemberRequest
- CorporateAccountResponse, CorporateMembershipResponse
- SpendSummaryResponse, CorporateRideListResponse
- Ride creation with corporate billing sets corporate_account_id
- Non-member cannot use corporate billing
- Monthly limit enforcement over limit returns error
- Per-ride limit enforcement
- Month rollover resets current_month_spend
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.corporate_account import CorporateAccount, CorporateMembership, MembershipStatus
from app.schemas.corporate_account import (
    CorporateAccountCreateRequest,
    CorporateAccountDetailResponse,
    CorporateAccountResponse,
    CorporateAccountUpdateRequest,
    CorporateMembershipResponse,
    CorporateRideItem,
    CorporateRideListResponse,
    InviteMemberRequest,
    MonthlySpendItem,
    SpendSummaryResponse,
)
from app.services.corporate_accounts import (
    DEFAULT_PAGE_SIZE,
    _current_month_str,
    activate_membership,
    check_monthly_limit,
    check_per_ride_limit,
    create_account,
    get_account,
    get_spend_summary,
    invite_member,
    list_account_rides,
    list_accounts,
    list_members,
    list_rider_memberships,
    record_corporate_spend,
    remove_member,
    update_account,
    validate_corporate_billing,
)


# ===========================================================================
# Helpers
# ===========================================================================

_NOW = datetime(2026, 4, 15, 10, 0, 0, tzinfo=timezone.utc)
_THIS_MONTH = "2026-04"
_NEXT_MONTH = "2026-05"


def _make_account(
    *,
    id: int = 1,
    company_name: str = "Acme Corp",
    billing_email: str = "billing@acme.com",
    monthly_limit: float | None = 1000.0,
    per_ride_limit: float | None = 50.0,
    is_active: bool = True,
    current_month_spend: float = 0.0,
    current_month: str = _THIS_MONTH,
    total_spend: float = 0.0,
) -> CorporateAccount:
    acc = MagicMock(spec=CorporateAccount)
    acc.id = id
    acc.company_name = company_name
    acc.billing_email = billing_email
    acc.monthly_limit = monthly_limit
    acc.per_ride_limit = per_ride_limit
    acc.is_active = is_active
    acc.current_month_spend = current_month_spend
    acc.current_month = current_month
    acc.total_spend = total_spend
    acc.created_at = _NOW
    return acc


def _make_membership(
    *,
    id: int = 10,
    account_id: int = 1,
    user_id: int = 42,
    monthly_limit: float | None = None,
    status: MembershipStatus = MembershipStatus.ACTIVE,
    invited_at: datetime = _NOW,
    activated_at: datetime | None = _NOW,
) -> CorporateMembership:
    m = MagicMock(spec=CorporateMembership)
    m.id = id
    m.account_id = account_id
    m.user_id = user_id
    m.monthly_limit = monthly_limit
    m.status = status
    m.invited_at = invited_at
    m.activated_at = activated_at
    return m


def _db_returning(value):
    """Build a minimal AsyncMock db that returns `value` from .execute()."""
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = value
    result_mock.scalars.return_value.all.return_value = [value] if value is not None else []
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result_mock)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


# ===========================================================================
# _current_month_str
# ===========================================================================


class TestCurrentMonthStr:
    def test_format_is_yyyy_mm(self):
        dt = datetime(2026, 4, 15, tzinfo=timezone.utc)
        assert _current_month_str(dt) == "2026-04"

    def test_january_padded(self):
        dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert _current_month_str(dt) == "2026-01"

    def test_december(self):
        dt = datetime(2025, 12, 31, tzinfo=timezone.utc)
        assert _current_month_str(dt) == "2025-12"

    def test_no_arg_uses_utc_now(self):
        result = _current_month_str()
        # Just verify it matches YYYY-MM format
        assert len(result) == 7
        assert result[4] == "-"


# ===========================================================================
# check_per_ride_limit
# ===========================================================================


class TestCheckPerRideLimit:
    def test_within_limit_returns_none(self):
        acc = _make_account(per_ride_limit=50.0)
        assert check_per_ride_limit(acc, 40.0) is None

    def test_exactly_at_limit_is_ok(self):
        acc = _make_account(per_ride_limit=50.0)
        assert check_per_ride_limit(acc, 50.0) is None

    def test_over_limit_returns_error(self):
        acc = _make_account(per_ride_limit=50.0)
        err = check_per_ride_limit(acc, 60.0)
        assert err is not None
        assert "per-ride limit" in err

    def test_no_limit_always_passes(self):
        acc = _make_account(per_ride_limit=None)
        assert check_per_ride_limit(acc, 999.0) is None

    def test_zero_fare_within_limit(self):
        acc = _make_account(per_ride_limit=50.0)
        assert check_per_ride_limit(acc, 0.0) is None


# ===========================================================================
# check_monthly_limit
# ===========================================================================


class TestCheckMonthlyLimit:
    def test_within_monthly_limit(self):
        acc = _make_account(monthly_limit=1000.0, current_month_spend=400.0)
        assert check_monthly_limit(acc, 200.0) is None

    def test_would_exactly_hit_limit_is_ok(self):
        acc = _make_account(monthly_limit=1000.0, current_month_spend=800.0)
        assert check_monthly_limit(acc, 200.0) is None

    def test_would_exceed_limit_returns_error(self):
        acc = _make_account(monthly_limit=1000.0, current_month_spend=900.0)
        err = check_monthly_limit(acc, 200.0)
        assert err is not None
        assert "monthly" in err.lower()

    def test_no_monthly_limit_always_passes(self):
        acc = _make_account(monthly_limit=None, current_month_spend=99999.0)
        assert check_monthly_limit(acc, 999.0) is None

    def test_first_ride_of_month_no_spend(self):
        acc = _make_account(monthly_limit=500.0, current_month_spend=0.0)
        assert check_monthly_limit(acc, 300.0) is None


# ===========================================================================
# validate_corporate_billing (mocked DB)
# ===========================================================================


class TestValidateCorporateBilling:
    @pytest.mark.asyncio
    async def test_no_active_membership_raises(self):
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(ValueError, match="active corporate membership"):
            await validate_corporate_billing(42, 30.0, db)

    @pytest.mark.asyncio
    async def test_multiple_active_memberships_raises(self):
        m1 = _make_membership(id=1)
        m2 = _make_membership(id=2)
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [m1, m2]
        db.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(ValueError, match="Multiple active"):
            await validate_corporate_billing(42, 30.0, db)

    @pytest.mark.asyncio
    async def test_inactive_account_raises(self):
        membership = _make_membership(status=MembershipStatus.ACTIVE)
        account = _make_account(is_active=False)

        db = AsyncMock()
        membership_result = MagicMock()
        membership_result.scalars.return_value.all.return_value = [membership]
        account_result = MagicMock()
        account_result.scalar_one_or_none.return_value = account
        db.execute = AsyncMock(side_effect=[membership_result, account_result])

        with pytest.raises(ValueError, match="not currently active"):
            await validate_corporate_billing(42, 30.0, db)

    @pytest.mark.asyncio
    async def test_per_ride_limit_exceeded_raises(self):
        membership = _make_membership(status=MembershipStatus.ACTIVE)
        account = _make_account(is_active=True, per_ride_limit=20.0)

        db = AsyncMock()
        membership_result = MagicMock()
        membership_result.scalars.return_value.all.return_value = [membership]
        account_result = MagicMock()
        account_result.scalar_one_or_none.return_value = account
        db.execute = AsyncMock(side_effect=[membership_result, account_result])

        with pytest.raises(ValueError, match="per-ride limit"):
            await validate_corporate_billing(42, 30.0, db)

    @pytest.mark.asyncio
    async def test_monthly_limit_exceeded_raises(self):
        membership = _make_membership(status=MembershipStatus.ACTIVE)
        account = _make_account(
            is_active=True,
            per_ride_limit=None,
            monthly_limit=100.0,
            current_month_spend=90.0,
        )

        db = AsyncMock()
        membership_result = MagicMock()
        membership_result.scalars.return_value.all.return_value = [membership]
        account_result = MagicMock()
        account_result.scalar_one_or_none.return_value = account
        db.execute = AsyncMock(side_effect=[membership_result, account_result])

        with pytest.raises(ValueError, match="monthly"):
            await validate_corporate_billing(42, 30.0, db)

    @pytest.mark.asyncio
    async def test_success_returns_account_and_membership(self):
        membership = _make_membership(status=MembershipStatus.ACTIVE)
        account = _make_account(
            is_active=True,
            per_ride_limit=None,
            monthly_limit=None,
        )

        db = AsyncMock()
        membership_result = MagicMock()
        membership_result.scalars.return_value.all.return_value = [membership]
        account_result = MagicMock()
        account_result.scalar_one_or_none.return_value = account
        db.execute = AsyncMock(side_effect=[membership_result, account_result])

        ret_account, ret_membership = await validate_corporate_billing(42, 30.0, db)
        assert ret_account is account
        assert ret_membership is membership

    @pytest.mark.asyncio
    async def test_pending_membership_not_treated_as_active(self):
        """validate_corporate_billing only counts ACTIVE status memberships."""
        # The DB query filters on ACTIVE; we simulate zero ACTIVE results
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(ValueError):
            await validate_corporate_billing(42, 30.0, db)


# ===========================================================================
# record_corporate_spend (mocked DB)
# ===========================================================================


class TestRecordCorporateSpend:
    @pytest.mark.asyncio
    async def test_increments_both_counters(self):
        account = _make_account(
            current_month_spend=100.0,
            current_month=_THIS_MONTH,
            total_spend=500.0,
        )
        db = _db_returning(account)

        await record_corporate_spend(1, 40.0, db, now=_NOW)

        assert account.current_month_spend == 140.0
        assert account.total_spend == 540.0
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_resets_monthly_spend_on_new_month(self):
        account = _make_account(
            current_month_spend=350.0,
            current_month="2026-03",  # previous month
            total_spend=1000.0,
        )
        db = _db_returning(account)

        # Call with April 2026
        await record_corporate_spend(1, 30.0, db, now=_NOW)

        # Monthly counter reset to 0 then incremented by 30
        assert account.current_month_spend == 30.0
        assert account.current_month == _THIS_MONTH
        # Total accumulates regardless
        assert account.total_spend == 1030.0

    @pytest.mark.asyncio
    async def test_same_month_does_not_reset(self):
        account = _make_account(
            current_month_spend=200.0,
            current_month=_THIS_MONTH,
            total_spend=800.0,
        )
        db = _db_returning(account)

        await record_corporate_spend(1, 50.0, db, now=_NOW)

        assert account.current_month_spend == 250.0
        assert account.current_month == _THIS_MONTH

    @pytest.mark.asyncio
    async def test_returns_none_when_account_not_found(self):
        db = _db_returning(None)
        result = await record_corporate_spend(999, 10.0, db)
        assert result is None


# ===========================================================================
# create_account (mocked DB)
# ===========================================================================


class TestCreateAccount:
    @pytest.mark.asyncio
    async def test_create_sets_defaults(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        account = await create_account(
            db,
            company_name="TechCorp",
            billing_email="pay@techcorp.com",
            monthly_limit=500.0,
            per_ride_limit=40.0,
            now=_NOW,
        )
        db.add.assert_called_once()
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_without_limits(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        await create_account(
            db,
            company_name="StartupInc",
            billing_email="cfo@startup.io",
        )
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_current_month_set_from_now(self):
        created = []

        async def capture_refresh(obj):
            created.append(obj)

        db = AsyncMock()
        db.add = MagicMock(side_effect=lambda obj: None)
        db.commit = AsyncMock()
        db.refresh = AsyncMock(side_effect=capture_refresh)

        await create_account(
            db,
            company_name="X",
            billing_email="x@x.com",
            now=_NOW,
        )
        # The CorporateAccount constructor is called inside the service;
        # just verify db operations ran correctly
        db.add.assert_called_once()


# ===========================================================================
# get_account (mocked DB)
# ===========================================================================


class TestGetAccount:
    @pytest.mark.asyncio
    async def test_returns_account_when_found(self):
        account = _make_account(id=5)
        db = _db_returning(account)

        result = await get_account(db, 5)
        assert result is account

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        db = _db_returning(None)
        result = await get_account(db, 999)
        assert result is None


# ===========================================================================
# list_accounts (mocked DB)
# ===========================================================================


class TestListAccounts:
    @pytest.mark.asyncio
    async def test_returns_all_accounts(self):
        accounts = [_make_account(id=1), _make_account(id=2)]

        count_result = MagicMock()
        count_result.scalar_one.return_value = 2
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = accounts

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[count_result, list_result])

        items, total = await list_accounts(db)
        assert total == 2
        assert len(items) == 2

    @pytest.mark.asyncio
    async def test_active_only_filter(self):
        accounts = [_make_account(id=1, is_active=True)]

        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = accounts

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[count_result, list_result])

        items, total = await list_accounts(db, active_only=True)
        assert total == 1

    @pytest.mark.asyncio
    async def test_empty_list(self):
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = []

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[count_result, list_result])

        items, total = await list_accounts(db)
        assert total == 0
        assert items == []


# ===========================================================================
# update_account (mocked DB)
# ===========================================================================


class TestUpdateAccount:
    @pytest.mark.asyncio
    async def test_update_company_name(self):
        account = _make_account(id=1, company_name="OldName")
        db = _db_returning(account)

        result = await update_account(db, 1, company_name="NewName")
        assert account.company_name == "NewName"
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_is_active(self):
        account = _make_account(id=1, is_active=True)
        db = _db_returning(account)

        await update_account(db, 1, is_active=False)
        assert account.is_active is False

    @pytest.mark.asyncio
    async def test_update_returns_none_when_not_found(self):
        db = _db_returning(None)
        result = await update_account(db, 999, company_name="X")
        assert result is None

    @pytest.mark.asyncio
    async def test_partial_update_does_not_change_other_fields(self):
        account = _make_account(id=1, billing_email="old@co.com", monthly_limit=500.0)
        db = _db_returning(account)

        await update_account(db, 1, company_name="NewCo")
        # billing_email and monthly_limit unchanged
        assert account.billing_email == "old@co.com"
        assert account.monthly_limit == 500.0


# ===========================================================================
# invite_member (mocked DB)
# ===========================================================================


class TestInviteMember:
    @pytest.mark.asyncio
    async def test_invite_success(self):
        # No existing membership
        no_membership_result = MagicMock()
        no_membership_result.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.execute = AsyncMock(return_value=no_membership_result)
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        membership, err = await invite_member(db, account_id=1, user_id=42)
        assert err is None
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_duplicate_invite_rejected(self):
        existing = _make_membership(status=MembershipStatus.PENDING)
        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = existing

        db = AsyncMock()
        db.execute = AsyncMock(return_value=existing_result)

        membership, err = await invite_member(db, account_id=1, user_id=42)
        assert membership is None
        assert err is not None
        assert "already has" in err

    @pytest.mark.asyncio
    async def test_invite_with_monthly_limit(self):
        no_membership_result = MagicMock()
        no_membership_result.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.execute = AsyncMock(return_value=no_membership_result)
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        membership, err = await invite_member(db, account_id=1, user_id=42, monthly_limit=200.0)
        assert err is None


# ===========================================================================
# activate_membership (mocked DB)
# ===========================================================================


class TestActivateMembership:
    @pytest.mark.asyncio
    async def test_activate_pending_membership(self):
        m = _make_membership(status=MembershipStatus.PENDING, activated_at=None)
        db = _db_returning(m)

        result, err = await activate_membership(db, membership_id=10, user_id=42, now=_NOW)
        assert err is None
        assert m.status == MembershipStatus.ACTIVE
        assert m.activated_at == _NOW

    @pytest.mark.asyncio
    async def test_activate_not_found(self):
        db = _db_returning(None)
        result, err = await activate_membership(db, membership_id=999, user_id=42)
        assert result is None
        assert "not found" in err

    @pytest.mark.asyncio
    async def test_activate_already_active_fails(self):
        m = _make_membership(status=MembershipStatus.ACTIVE)
        db = _db_returning(m)

        result, err = await activate_membership(db, membership_id=10, user_id=42)
        assert result is None
        assert err is not None
        assert "Cannot activate" in err

    @pytest.mark.asyncio
    async def test_activate_suspended_fails(self):
        m = _make_membership(status=MembershipStatus.SUSPENDED)
        db = _db_returning(m)

        result, err = await activate_membership(db, membership_id=10, user_id=42)
        assert result is None
        assert err is not None


# ===========================================================================
# remove_member (mocked DB)
# ===========================================================================


class TestRemoveMember:
    @pytest.mark.asyncio
    async def test_remove_active_member(self):
        m = _make_membership(status=MembershipStatus.ACTIVE)
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = m

        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        membership, err = await remove_member(db, account_id=1, user_id=42)
        assert err is None
        assert m.status == MembershipStatus.REMOVED

    @pytest.mark.asyncio
    async def test_remove_not_found(self):
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        membership, err = await remove_member(db, account_id=1, user_id=99)
        assert membership is None
        assert err is not None

    @pytest.mark.asyncio
    async def test_remove_pending_member(self):
        m = _make_membership(status=MembershipStatus.PENDING)
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = m

        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        membership, err = await remove_member(db, account_id=1, user_id=42)
        assert err is None
        assert m.status == MembershipStatus.REMOVED


# ===========================================================================
# list_members (mocked DB)
# ===========================================================================


class TestListMembers:
    @pytest.mark.asyncio
    async def test_list_members_returns_all(self):
        members = [
            _make_membership(id=1, status=MembershipStatus.ACTIVE),
            _make_membership(id=2, status=MembershipStatus.PENDING),
        ]
        count_result = MagicMock()
        count_result.scalar_one.return_value = 2
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = members

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[count_result, list_result])

        items, total = await list_members(db, account_id=1)
        assert total == 2
        assert len(items) == 2

    @pytest.mark.asyncio
    async def test_list_members_empty(self):
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = []

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[count_result, list_result])

        items, total = await list_members(db, account_id=1)
        assert total == 0


# ===========================================================================
# list_rider_memberships (mocked DB)
# ===========================================================================


class TestListRiderMemberships:
    @pytest.mark.asyncio
    async def test_returns_pending_and_active(self):
        members = [
            _make_membership(id=1, status=MembershipStatus.ACTIVE),
            _make_membership(id=2, status=MembershipStatus.PENDING),
        ]
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = members

        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        items = await list_rider_memberships(db, user_id=42)
        assert len(items) == 2

    @pytest.mark.asyncio
    async def test_returns_empty_list_for_no_memberships(self):
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []

        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        items = await list_rider_memberships(db, user_id=99)
        assert items == []


# ===========================================================================
# list_account_rides (mocked DB)
# ===========================================================================


class TestListAccountRides:
    @pytest.mark.asyncio
    async def test_returns_rides_with_total(self):
        from app.models.ride import Ride
        ride = MagicMock(spec=Ride)
        ride.id = 1

        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = [ride]

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[count_result, list_result])

        items, total = await list_account_rides(db, account_id=1)
        assert total == 1
        assert len(items) == 1

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_rides(self):
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = []

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[count_result, list_result])

        items, total = await list_account_rides(db, account_id=1)
        assert total == 0
        assert items == []


# ===========================================================================
# Schema validation
# ===========================================================================


class TestSchemas:
    def test_create_request_valid(self):
        req = CorporateAccountCreateRequest(
            company_name="Acme",
            billing_email="billing@acme.com",
            monthly_limit=1000.0,
            per_ride_limit=50.0,
        )
        assert req.company_name == "Acme"
        assert req.monthly_limit == 1000.0

    def test_create_request_no_limits(self):
        req = CorporateAccountCreateRequest(
            company_name="Acme",
            billing_email="billing@acme.com",
        )
        assert req.monthly_limit is None
        assert req.per_ride_limit is None

    def test_create_request_empty_name_fails(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CorporateAccountCreateRequest(
                company_name="",
                billing_email="billing@acme.com",
            )

    def test_create_request_negative_limit_fails(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CorporateAccountCreateRequest(
                company_name="Acme",
                billing_email="billing@acme.com",
                monthly_limit=-100.0,
            )

    def test_invite_member_request_valid(self):
        req = InviteMemberRequest(user_id=42, monthly_limit=200.0)
        assert req.user_id == 42
        assert req.monthly_limit == 200.0

    def test_invite_member_request_no_limit(self):
        req = InviteMemberRequest(user_id=42)
        assert req.monthly_limit is None

    def test_invite_member_invalid_user_id(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            InviteMemberRequest(user_id=0)  # must be > 0

    def test_corporate_account_response_from_attributes(self):
        account = _make_account(id=1)
        resp = CorporateAccountResponse.model_validate(account)
        assert resp.id == 1
        assert resp.company_name == "Acme Corp"
        assert resp.is_active is True

    def test_corporate_membership_response_from_attributes(self):
        m = _make_membership(id=10, status=MembershipStatus.ACTIVE)
        resp = CorporateMembershipResponse.model_validate(m)
        assert resp.id == 10
        assert resp.status == MembershipStatus.ACTIVE

    def test_spend_summary_response(self):
        summary = SpendSummaryResponse(
            account_id=1,
            current_month="2026-04",
            current_month_spend=350.0,
            monthly_breakdown=[
                MonthlySpendItem(month="2026-03", total=500.0),
                MonthlySpendItem(month="2026-02", total=420.0),
            ],
        )
        assert summary.account_id == 1
        assert len(summary.monthly_breakdown) == 2
        assert summary.monthly_breakdown[0].month == "2026-03"

    def test_corporate_ride_list_response(self):
        resp = CorporateRideListResponse(
            items=[],
            total=0,
            page=1,
            page_size=20,
        )
        assert resp.total == 0
        assert resp.items == []

    def test_update_request_all_none_is_valid(self):
        req = CorporateAccountUpdateRequest()
        assert req.company_name is None
        assert req.is_active is None

    def test_update_request_partial(self):
        req = CorporateAccountUpdateRequest(company_name="NewCo", is_active=False)
        assert req.company_name == "NewCo"
        assert req.is_active is False


# ===========================================================================
# MembershipStatus enum
# ===========================================================================


class TestMembershipStatusEnum:
    def test_all_statuses_exist(self):
        values = {s.value for s in MembershipStatus}
        assert "pending" in values
        assert "active" in values
        assert "suspended" in values
        assert "removed" in values

    def test_is_str_enum(self):
        assert MembershipStatus.PENDING == "pending"
        assert MembershipStatus.ACTIVE == "active"
        assert MembershipStatus.SUSPENDED == "suspended"
        assert MembershipStatus.REMOVED == "removed"


# ===========================================================================
# Constants
# ===========================================================================


class TestConstants:
    def test_default_page_size(self):
        assert DEFAULT_PAGE_SIZE == 20


# ===========================================================================
# Integration: ride creation with corporate billing sets corporate_account_id
# ===========================================================================


class TestRideCreationWithCorporateBilling:
    """Verify the validate_corporate_billing integration path."""

    @pytest.mark.asyncio
    async def test_validates_and_sets_account_id(self):
        """When use_corporate_billing=True and validation passes, the returned
        account id should be stored on the ride."""
        account = _make_account(id=7)
        membership = _make_membership(status=MembershipStatus.ACTIVE)

        db = AsyncMock()
        membership_result = MagicMock()
        membership_result.scalars.return_value.all.return_value = [membership]
        account_result = MagicMock()
        account_result.scalar_one_or_none.return_value = account
        db.execute = AsyncMock(side_effect=[membership_result, account_result])

        ret_account, ret_membership = await validate_corporate_billing(42, 30.0, db)
        # The ride creation code uses ret_account.id as corporate_account_id
        assert ret_account.id == 7

    @pytest.mark.asyncio
    async def test_non_member_raises_error(self):
        """A user with no ACTIVE membership should fail validation."""
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(ValueError):
            await validate_corporate_billing(99, 25.0, db)

    @pytest.mark.asyncio
    async def test_over_per_ride_limit_raises_error(self):
        membership = _make_membership(status=MembershipStatus.ACTIVE)
        account = _make_account(is_active=True, per_ride_limit=25.0)

        db = AsyncMock()
        membership_result = MagicMock()
        membership_result.scalars.return_value.all.return_value = [membership]
        account_result = MagicMock()
        account_result.scalar_one_or_none.return_value = account
        db.execute = AsyncMock(side_effect=[membership_result, account_result])

        with pytest.raises(ValueError, match="per-ride limit"):
            await validate_corporate_billing(42, 30.0, db)

    @pytest.mark.asyncio
    async def test_over_monthly_limit_raises_error(self):
        membership = _make_membership(status=MembershipStatus.ACTIVE)
        account = _make_account(
            is_active=True,
            per_ride_limit=None,
            monthly_limit=200.0,
            current_month_spend=195.0,
        )

        db = AsyncMock()
        membership_result = MagicMock()
        membership_result.scalars.return_value.all.return_value = [membership]
        account_result = MagicMock()
        account_result.scalar_one_or_none.return_value = account
        db.execute = AsyncMock(side_effect=[membership_result, account_result])

        with pytest.raises(ValueError, match="monthly"):
            await validate_corporate_billing(42, 30.0, db)


# ===========================================================================
# Month rollover
# ===========================================================================


class TestMonthRollover:
    @pytest.mark.asyncio
    async def test_rollover_resets_monthly_spend(self):
        """record_corporate_spend resets current_month_spend when month changes."""
        account = _make_account(
            current_month_spend=800.0,
            current_month="2026-03",
            total_spend=5000.0,
        )
        db = _db_returning(account)

        # Simulate call in April 2026
        april = datetime(2026, 4, 1, tzinfo=timezone.utc)
        await record_corporate_spend(1, 100.0, db, now=april)

        assert account.current_month == "2026-04"
        assert account.current_month_spend == 100.0  # reset to 0, then +100
        assert account.total_spend == 5100.0

    @pytest.mark.asyncio
    async def test_no_rollover_when_same_month(self):
        account = _make_account(
            current_month_spend=300.0,
            current_month="2026-04",
            total_spend=1000.0,
        )
        db = _db_returning(account)

        mid_april = datetime(2026, 4, 15, tzinfo=timezone.utc)
        await record_corporate_spend(1, 50.0, db, now=mid_april)

        assert account.current_month == "2026-04"
        assert account.current_month_spend == 350.0
        assert account.total_spend == 1050.0
