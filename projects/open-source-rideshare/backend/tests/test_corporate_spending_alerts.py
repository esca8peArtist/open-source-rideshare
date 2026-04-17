"""Tests for corporate spending limit alerts.

Covers:
  - Pydantic schemas (SpendingAlertOut, SpendingAlertsListResponse,
    MemberSpendStatus, SpendingAlertsSummary)
  - Service: check_and_create_alerts (mocked DB)
  - Service: get_account_alerts (mocked DB)
  - Service: get_member_alerts (mocked DB)
  - Service: get_alerts_summary (mocked DB)
  - API endpoints:
      POST /corporate/{account_id}/spending-alerts/check
      GET  /corporate/{account_id}/spending-alerts
      GET  /corporate/{account_id}/spending-alerts/summary
      GET  /corporate/{account_id}/spending-alerts/my
      GET  /admin/corporate/spending-alerts

No live database is used.  All DB interactions are mocked with AsyncMock /
MagicMock following the same pattern as test_corporate_invoice_due_date.py.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.corporate_spending_alert import AlertType
from app.schemas.corporate_spending_alert import (
    MemberSpendStatus,
    SpendingAlertOut,
    SpendingAlertsListResponse,
    SpendingAlertsSummary,
)

TODAY = date(2026, 4, 17)
YEAR = 2026
MONTH = 4


# ---------------------------------------------------------------------------
# Mock factories
# ---------------------------------------------------------------------------


def _make_account(
    account_id: int = 1,
    monthly_budget_limit: Decimal | None = Decimal("1000.00"),
) -> MagicMock:
    a = MagicMock()
    a.id = account_id
    a.monthly_budget_limit = monthly_budget_limit
    return a


def _make_member(
    member_id: int = 10,
    user_id: int = 100,
    account_id: int = 1,
    monthly_spend_limit: Decimal | None = Decimal("500.00"),
    is_active: bool = True,
) -> MagicMock:
    m = MagicMock()
    m.id = member_id
    m.user_id = user_id
    m.account_id = account_id
    m.monthly_spend_limit = monthly_spend_limit
    m.is_active = is_active
    from app.models.corporate import MemberRole
    m.role = MemberRole.ADMIN
    return m


def _make_invoice(
    invoice_id: int = 1,
    account_id: int = 1,
    total_amount: Decimal = Decimal("0.00"),
) -> MagicMock:
    inv = MagicMock()
    inv.id = invoice_id
    inv.account_id = account_id
    inv.total_amount = total_amount
    return inv


def _make_alert(
    alert_id: int = 1,
    account_id: int = 1,
    member_id: int | None = None,
    alert_type: AlertType = AlertType.WARNING_75PCT,
    threshold_pct: int = 75,
    current_spend_usd: Decimal = Decimal("750.00"),
    limit_usd: Decimal = Decimal("1000.00"),
    period_year: int = YEAR,
    period_month: int = MONTH,
) -> MagicMock:
    a = MagicMock()
    a.id = alert_id
    a.account_id = account_id
    a.member_id = member_id
    a.alert_type = alert_type
    a.threshold_pct = threshold_pct
    a.current_spend_usd = current_spend_usd
    a.limit_usd = limit_usd
    a.period_year = period_year
    a.period_month = period_month
    from datetime import datetime, timezone
    a.created_at = datetime(2026, 4, 17, 12, 0, 0, tzinfo=timezone.utc)
    return a


def _db_with_scalar_one_or_none(*values):
    """AsyncSession mock: scalar_one_or_none returns values in sequence."""
    db = AsyncMock()
    results = []
    for v in values:
        r = MagicMock()
        r.scalar_one_or_none.return_value = v
        results.append(r)
    db.execute = AsyncMock(side_effect=results)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _db_with_scalars(*lists_of_rows):
    """AsyncSession mock: scalars().all() returns lists in sequence."""
    db = AsyncMock()
    results = []
    for row_list in lists_of_rows:
        result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = row_list
        result.scalars.return_value = scalars_mock
        results.append(result)
    db.execute = AsyncMock(side_effect=results)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestSpendingAlertOutSchema:
    """Pydantic validation for SpendingAlertOut."""

    def test_basic_construction(self):
        from datetime import datetime, timezone

        alert = SpendingAlertOut(
            id=1,
            account_id=1,
            member_id=None,
            alert_type=AlertType.WARNING_75PCT,
            threshold_pct=75,
            current_spend_usd=Decimal("750.00"),
            limit_usd=Decimal("1000.00"),
            period_year=YEAR,
            period_month=MONTH,
            created_at=datetime(2026, 4, 17, 12, 0, 0, tzinfo=timezone.utc),
        )
        assert alert.id == 1
        assert alert.alert_type == AlertType.WARNING_75PCT
        assert alert.threshold_pct == 75

    def test_from_attributes_config(self):
        assert SpendingAlertOut.model_config.get("from_attributes") is True

    def test_member_id_nullable(self):
        from datetime import datetime, timezone

        alert = SpendingAlertOut(
            id=2,
            account_id=1,
            member_id=None,
            alert_type=AlertType.LIMIT_REACHED,
            threshold_pct=100,
            current_spend_usd=Decimal("1000.00"),
            limit_usd=Decimal("1000.00"),
            period_year=YEAR,
            period_month=MONTH,
            created_at=datetime(2026, 4, 17, tzinfo=timezone.utc),
        )
        assert alert.member_id is None

    def test_member_id_with_value(self):
        from datetime import datetime, timezone

        alert = SpendingAlertOut(
            id=3,
            account_id=1,
            member_id=42,
            alert_type=AlertType.WARNING_90PCT,
            threshold_pct=90,
            current_spend_usd=Decimal("450.00"),
            limit_usd=Decimal("500.00"),
            period_year=YEAR,
            period_month=MONTH,
            created_at=datetime(2026, 4, 17, tzinfo=timezone.utc),
        )
        assert alert.member_id == 42

    def test_all_alert_types_valid(self):
        from datetime import datetime, timezone

        for at in AlertType:
            alert = SpendingAlertOut(
                id=1,
                account_id=1,
                member_id=None,
                alert_type=at,
                threshold_pct=75,
                current_spend_usd=Decimal("0.00"),
                limit_usd=Decimal("100.00"),
                period_year=YEAR,
                period_month=MONTH,
                created_at=datetime(2026, 4, 17, tzinfo=timezone.utc),
            )
            assert alert.alert_type == at


class TestSpendingAlertsListResponseSchema:
    """Pydantic validation for SpendingAlertsListResponse."""

    def test_empty_list(self):
        resp = SpendingAlertsListResponse(alerts=[], total=0)
        assert resp.alerts == []
        assert resp.total == 0

    def test_total_field(self):
        resp = SpendingAlertsListResponse(alerts=[], total=5)
        assert resp.total == 5


class TestMemberSpendStatusSchema:
    """Pydantic validation for MemberSpendStatus."""

    def test_basic_construction(self):
        ms = MemberSpendStatus(
            member_id=10,
            current_spend_usd=Decimal("750.00"),
            limit_usd=Decimal("1000.00"),
            pct_used=75.0,
            highest_alert=AlertType.WARNING_75PCT,
        )
        assert ms.member_id == 10
        assert ms.pct_used == 75.0
        assert ms.highest_alert == AlertType.WARNING_75PCT

    def test_no_alert_none(self):
        ms = MemberSpendStatus(
            member_id=10,
            current_spend_usd=Decimal("100.00"),
            limit_usd=Decimal("1000.00"),
            pct_used=10.0,
            highest_alert=None,
        )
        assert ms.highest_alert is None


class TestSpendingAlertsSummarySchema:
    """Pydantic validation for SpendingAlertsSummary."""

    def test_basic_construction(self):
        s = SpendingAlertsSummary(
            account_id=1,
            period_year=YEAR,
            period_month=MONTH,
            account_spend_usd=Decimal("500.00"),
            account_limit_usd=Decimal("1000.00"),
            account_pct_used=50.0,
            account_alert=None,
            members_near_limit=[],
            members_at_limit=[],
            members_over_limit=[],
        )
        assert s.account_id == 1
        assert s.account_pct_used == 50.0
        assert s.members_near_limit == []

    def test_no_limit_is_none(self):
        s = SpendingAlertsSummary(
            account_id=2,
            period_year=YEAR,
            period_month=MONTH,
            account_spend_usd=Decimal("200.00"),
            account_limit_usd=None,
            account_pct_used=None,
            account_alert=None,
            members_near_limit=[],
            members_at_limit=[],
            members_over_limit=[],
        )
        assert s.account_limit_usd is None
        assert s.account_pct_used is None


# ---------------------------------------------------------------------------
# Service: _alerts_for_spend helper
# ---------------------------------------------------------------------------


class TestAlertsForSpend:
    """Unit tests for the internal _alerts_for_spend helper."""

    def test_no_limit_returns_empty(self):
        from app.services.corporate_spending_alert_service import _alerts_for_spend

        result = _alerts_for_spend(Decimal("1000.00"), Decimal("0"), set())
        assert result == []

    def test_below_75_pct_no_alert(self):
        from app.services.corporate_spending_alert_service import _alerts_for_spend

        result = _alerts_for_spend(Decimal("740.00"), Decimal("1000.00"), set())
        assert result == []

    def test_exactly_75_pct_triggers_warning(self):
        from app.services.corporate_spending_alert_service import _alerts_for_spend

        result = _alerts_for_spend(Decimal("750.00"), Decimal("1000.00"), set())
        assert any(at == AlertType.WARNING_75PCT for _, at in result)

    def test_90_pct_triggers_both_warnings(self):
        from app.services.corporate_spending_alert_service import _alerts_for_spend

        result = _alerts_for_spend(Decimal("900.00"), Decimal("1000.00"), set())
        types = {at for _, at in result}
        assert AlertType.WARNING_75PCT in types
        assert AlertType.WARNING_90PCT in types

    def test_100_pct_triggers_all_thresholds(self):
        from app.services.corporate_spending_alert_service import _alerts_for_spend

        result = _alerts_for_spend(Decimal("1000.00"), Decimal("1000.00"), set())
        types = {at for _, at in result}
        assert types == {AlertType.WARNING_75PCT, AlertType.WARNING_90PCT, AlertType.LIMIT_REACHED}

    def test_already_fired_not_repeated(self):
        from app.services.corporate_spending_alert_service import _alerts_for_spend

        already = {AlertType.WARNING_75PCT}
        result = _alerts_for_spend(Decimal("900.00"), Decimal("1000.00"), already)
        types = {at for _, at in result}
        assert AlertType.WARNING_75PCT not in types
        assert AlertType.WARNING_90PCT in types

    def test_all_already_fired_returns_empty(self):
        from app.services.corporate_spending_alert_service import _alerts_for_spend

        already = {AlertType.WARNING_75PCT, AlertType.WARNING_90PCT, AlertType.LIMIT_REACHED}
        result = _alerts_for_spend(Decimal("1500.00"), Decimal("1000.00"), already)
        assert result == []


# ---------------------------------------------------------------------------
# Service: check_and_create_alerts
# ---------------------------------------------------------------------------


class TestCheckAndCreateAlerts:
    """Tests for check_and_create_alerts with mocked DB."""

    @pytest.mark.asyncio
    async def test_no_limit_creates_no_alerts(self):
        from app.services.corporate_spending_alert_service import check_and_create_alerts

        account = _make_account(monthly_budget_limit=None)
        # calls: get_account, compute_spend (invoices), get_active_members
        db = _db_with_scalars(
            [account],   # _get_account
            [],           # _compute_account_spend invoices
            [],           # _get_active_members
        )
        # _get_account uses scalar_one_or_none
        db2 = AsyncMock()
        results = []
        # account fetch
        r0 = MagicMock(); r0.scalar_one_or_none.return_value = account; results.append(r0)
        # invoices for spend
        r1 = MagicMock(); s1 = MagicMock(); s1.all.return_value = []; r1.scalars.return_value = s1; results.append(r1)
        # active members
        r2 = MagicMock(); s2 = MagicMock(); s2.all.return_value = []; r2.scalars.return_value = s2; results.append(r2)
        db2.execute = AsyncMock(side_effect=results)
        db2.add = MagicMock()
        db2.commit = AsyncMock()
        db2.refresh = AsyncMock()

        new_alerts = await check_and_create_alerts(db2, account_id=1, as_of_date=TODAY)
        assert new_alerts == []
        db2.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_account_spend_above_75_creates_alert(self):
        from app.services.corporate_spending_alert_service import check_and_create_alerts

        account = _make_account(monthly_budget_limit=Decimal("1000.00"))
        invoice = _make_invoice(total_amount=Decimal("800.00"))
        db = AsyncMock()
        results = []
        # _get_account
        r0 = MagicMock(); r0.scalar_one_or_none.return_value = account; results.append(r0)
        # _compute_account_spend: invoices
        r1 = MagicMock(); s1 = MagicMock(); s1.all.return_value = [invoice]; r1.scalars.return_value = s1; results.append(r1)
        # _get_active_members
        r2 = MagicMock(); s2 = MagicMock(); s2.all.return_value = []; r2.scalars.return_value = s2; results.append(r2)
        # _existing_alert_types for account
        r3 = MagicMock(); s3 = MagicMock(); s3.all.return_value = []; r3.scalars.return_value = s3; results.append(r3)
        db.execute = AsyncMock(side_effect=results)
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        new_alerts = await check_and_create_alerts(db, account_id=1, as_of_date=TODAY)
        # 800/1000 = 80% -> warning_75pct only
        assert len(new_alerts) == 1
        assert new_alerts[0].alert_type == AlertType.WARNING_75PCT
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_spend_above_90_creates_two_alerts(self):
        from app.services.corporate_spending_alert_service import check_and_create_alerts

        account = _make_account(monthly_budget_limit=Decimal("1000.00"))
        invoice = _make_invoice(total_amount=Decimal("920.00"))
        db = AsyncMock()
        results = []
        r0 = MagicMock(); r0.scalar_one_or_none.return_value = account; results.append(r0)
        r1 = MagicMock(); s1 = MagicMock(); s1.all.return_value = [invoice]; r1.scalars.return_value = s1; results.append(r1)
        r2 = MagicMock(); s2 = MagicMock(); s2.all.return_value = []; r2.scalars.return_value = s2; results.append(r2)
        r3 = MagicMock(); s3 = MagicMock(); s3.all.return_value = []; r3.scalars.return_value = s3; results.append(r3)
        db.execute = AsyncMock(side_effect=results)
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        new_alerts = await check_and_create_alerts(db, account_id=1, as_of_date=TODAY)
        types = {a.alert_type for a in new_alerts}
        assert AlertType.WARNING_75PCT in types
        assert AlertType.WARNING_90PCT in types

    @pytest.mark.asyncio
    async def test_100_pct_creates_three_alerts(self):
        from app.services.corporate_spending_alert_service import check_and_create_alerts

        account = _make_account(monthly_budget_limit=Decimal("1000.00"))
        invoice = _make_invoice(total_amount=Decimal("1000.00"))
        db = AsyncMock()
        results = []
        r0 = MagicMock(); r0.scalar_one_or_none.return_value = account; results.append(r0)
        r1 = MagicMock(); s1 = MagicMock(); s1.all.return_value = [invoice]; r1.scalars.return_value = s1; results.append(r1)
        r2 = MagicMock(); s2 = MagicMock(); s2.all.return_value = []; r2.scalars.return_value = s2; results.append(r2)
        r3 = MagicMock(); s3 = MagicMock(); s3.all.return_value = []; r3.scalars.return_value = s3; results.append(r3)
        db.execute = AsyncMock(side_effect=results)
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        new_alerts = await check_and_create_alerts(db, account_id=1, as_of_date=TODAY)
        types = {a.alert_type for a in new_alerts}
        assert types == {AlertType.WARNING_75PCT, AlertType.WARNING_90PCT, AlertType.LIMIT_REACHED}

    @pytest.mark.asyncio
    async def test_already_fired_not_duplicated(self):
        from app.services.corporate_spending_alert_service import check_and_create_alerts

        account = _make_account(monthly_budget_limit=Decimal("1000.00"))
        invoice = _make_invoice(total_amount=Decimal("800.00"))
        existing_alert = _make_alert(alert_type=AlertType.WARNING_75PCT)
        db = AsyncMock()
        results = []
        r0 = MagicMock(); r0.scalar_one_or_none.return_value = account; results.append(r0)
        r1 = MagicMock(); s1 = MagicMock(); s1.all.return_value = [invoice]; r1.scalars.return_value = s1; results.append(r1)
        r2 = MagicMock(); s2 = MagicMock(); s2.all.return_value = []; r2.scalars.return_value = s2; results.append(r2)
        # existing alerts already has WARNING_75PCT
        r3 = MagicMock(); s3 = MagicMock(); s3.all.return_value = [existing_alert]; r3.scalars.return_value = s3; results.append(r3)
        db.execute = AsyncMock(side_effect=results)
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        new_alerts = await check_and_create_alerts(db, account_id=1, as_of_date=TODAY)
        assert new_alerts == []
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_account_not_found_raises_404(self):
        from app.services.corporate_spending_alert_service import check_and_create_alerts
        from fastapi import HTTPException

        db = AsyncMock()
        r0 = MagicMock(); r0.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(side_effect=[r0])

        with pytest.raises(HTTPException) as exc_info:
            await check_and_create_alerts(db, account_id=999, as_of_date=TODAY)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_defaults_to_today(self):
        """as_of_date=None falls back to date.today()."""
        from app.services.corporate_spending_alert_service import check_and_create_alerts

        account = _make_account(monthly_budget_limit=None)
        db = AsyncMock()
        results = []
        r0 = MagicMock(); r0.scalar_one_or_none.return_value = account; results.append(r0)
        r1 = MagicMock(); s1 = MagicMock(); s1.all.return_value = []; r1.scalars.return_value = s1; results.append(r1)
        r2 = MagicMock(); s2 = MagicMock(); s2.all.return_value = []; r2.scalars.return_value = s2; results.append(r2)
        db.execute = AsyncMock(side_effect=results)
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        with patch("app.services.corporate_spending_alert_service.date") as mock_date:
            mock_date.today.return_value = TODAY
            new_alerts = await check_and_create_alerts(db, account_id=1, as_of_date=None)
        assert new_alerts == []

    @pytest.mark.asyncio
    async def test_member_alert_created_when_limit_set(self):
        from app.services.corporate_spending_alert_service import check_and_create_alerts

        # Account has no limit; member has limit 100 and spend is 800 / 1 member = 800
        account = _make_account(monthly_budget_limit=None)
        member = _make_member(monthly_spend_limit=Decimal("100.00"))
        invoice = _make_invoice(total_amount=Decimal("800.00"))
        db = AsyncMock()
        results = []
        r0 = MagicMock(); r0.scalar_one_or_none.return_value = account; results.append(r0)
        r1 = MagicMock(); s1 = MagicMock(); s1.all.return_value = [invoice]; r1.scalars.return_value = s1; results.append(r1)
        r2 = MagicMock(); s2 = MagicMock(); s2.all.return_value = [member]; r2.scalars.return_value = s2; results.append(r2)
        # _existing_alert_types for member
        r3 = MagicMock(); s3 = MagicMock(); s3.all.return_value = []; r3.scalars.return_value = s3; results.append(r3)
        db.execute = AsyncMock(side_effect=results)
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        new_alerts = await check_and_create_alerts(db, account_id=1, as_of_date=TODAY)
        # 800 / 1 member = 800, limit 100 -> 800% -> all 3 thresholds
        assert len(new_alerts) == 3
        assert new_alerts[0].member_id == member.id


# ---------------------------------------------------------------------------
# Service: get_account_alerts
# ---------------------------------------------------------------------------


class TestGetAccountAlerts:
    """Tests for get_account_alerts with mocked DB."""

    @pytest.mark.asyncio
    async def test_admin_can_list_alerts(self):
        from app.services.corporate_spending_alert_service import get_account_alerts

        account = _make_account()
        admin_member = _make_member(user_id=1)
        alert = _make_alert()
        db = AsyncMock()
        results = []
        r0 = MagicMock(); r0.scalar_one_or_none.return_value = account; results.append(r0)
        r1 = MagicMock(); r1.scalar_one_or_none.return_value = admin_member; results.append(r1)
        r2 = MagicMock(); s2 = MagicMock(); s2.all.return_value = [alert]; r2.scalars.return_value = s2; results.append(r2)
        db.execute = AsyncMock(side_effect=results)

        result = await get_account_alerts(db, account_id=1, requesting_user_id=1, year=YEAR, month=MONTH)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_non_admin_raises_403(self):
        from app.services.corporate_spending_alert_service import get_account_alerts
        from fastapi import HTTPException

        account = _make_account()
        db = AsyncMock()
        results = []
        r0 = MagicMock(); r0.scalar_one_or_none.return_value = account; results.append(r0)
        r1 = MagicMock(); r1.scalar_one_or_none.return_value = None; results.append(r1)  # not admin
        db.execute = AsyncMock(side_effect=results)

        with pytest.raises(HTTPException) as exc_info:
            await get_account_alerts(db, account_id=1, requesting_user_id=99, year=YEAR, month=MONTH)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_account_not_found_raises_404(self):
        from app.services.corporate_spending_alert_service import get_account_alerts
        from fastapi import HTTPException

        db = AsyncMock()
        r0 = MagicMock(); r0.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(side_effect=[r0])

        with pytest.raises(HTTPException) as exc_info:
            await get_account_alerts(db, account_id=999, requesting_user_id=1, year=YEAR, month=MONTH)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_empty_period_returns_empty_list(self):
        from app.services.corporate_spending_alert_service import get_account_alerts

        account = _make_account()
        admin_member = _make_member(user_id=1)
        db = AsyncMock()
        results = []
        r0 = MagicMock(); r0.scalar_one_or_none.return_value = account; results.append(r0)
        r1 = MagicMock(); r1.scalar_one_or_none.return_value = admin_member; results.append(r1)
        r2 = MagicMock(); s2 = MagicMock(); s2.all.return_value = []; r2.scalars.return_value = s2; results.append(r2)
        db.execute = AsyncMock(side_effect=results)

        result = await get_account_alerts(db, account_id=1, requesting_user_id=1, year=YEAR, month=MONTH)
        assert result == []


# ---------------------------------------------------------------------------
# Service: get_member_alerts
# ---------------------------------------------------------------------------


class TestGetMemberAlerts:
    """Tests for get_member_alerts with mocked DB."""

    @pytest.mark.asyncio
    async def test_member_can_see_own_alerts(self):
        from app.services.corporate_spending_alert_service import get_member_alerts

        account = _make_account()
        member = _make_member(member_id=10, user_id=1)
        alert = _make_alert(member_id=10)
        db = AsyncMock()
        results = []
        r0 = MagicMock(); r0.scalar_one_or_none.return_value = account; results.append(r0)
        r1 = MagicMock(); r1.scalar_one_or_none.return_value = member; results.append(r1)
        r2 = MagicMock(); s2 = MagicMock(); s2.all.return_value = [alert]; r2.scalars.return_value = s2; results.append(r2)
        db.execute = AsyncMock(side_effect=results)

        result = await get_member_alerts(
            db, account_id=1, member_id=10, requesting_user_id=1, year=YEAR, month=MONTH
        )
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_member_cannot_see_other_member_alerts(self):
        from app.services.corporate_spending_alert_service import get_member_alerts
        from fastapi import HTTPException

        account = _make_account()
        # Requesting user is member 10, but asking for member 20's alerts
        member = _make_member(member_id=10, user_id=1)
        db = AsyncMock()
        results = []
        r0 = MagicMock(); r0.scalar_one_or_none.return_value = account; results.append(r0)
        r1 = MagicMock(); r1.scalar_one_or_none.return_value = member; results.append(r1)
        db.execute = AsyncMock(side_effect=results)

        with pytest.raises(HTTPException) as exc_info:
            await get_member_alerts(
                db, account_id=1, member_id=20, requesting_user_id=1, year=YEAR, month=MONTH
            )
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_non_member_raises_403(self):
        from app.services.corporate_spending_alert_service import get_member_alerts
        from fastapi import HTTPException

        account = _make_account()
        db = AsyncMock()
        results = []
        r0 = MagicMock(); r0.scalar_one_or_none.return_value = account; results.append(r0)
        r1 = MagicMock(); r1.scalar_one_or_none.return_value = None; results.append(r1)
        db.execute = AsyncMock(side_effect=results)

        with pytest.raises(HTTPException) as exc_info:
            await get_member_alerts(
                db, account_id=1, member_id=10, requesting_user_id=999, year=YEAR, month=MONTH
            )
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_empty_alerts_returns_empty_list(self):
        from app.services.corporate_spending_alert_service import get_member_alerts

        account = _make_account()
        member = _make_member(member_id=10, user_id=1)
        db = AsyncMock()
        results = []
        r0 = MagicMock(); r0.scalar_one_or_none.return_value = account; results.append(r0)
        r1 = MagicMock(); r1.scalar_one_or_none.return_value = member; results.append(r1)
        r2 = MagicMock(); s2 = MagicMock(); s2.all.return_value = []; r2.scalars.return_value = s2; results.append(r2)
        db.execute = AsyncMock(side_effect=results)

        result = await get_member_alerts(
            db, account_id=1, member_id=10, requesting_user_id=1, year=YEAR, month=MONTH
        )
        assert result == []


# ---------------------------------------------------------------------------
# Service: get_alerts_summary
# ---------------------------------------------------------------------------


class TestGetAlertsSummary:
    """Tests for get_alerts_summary with mocked DB."""

    @pytest.mark.asyncio
    async def test_no_members_no_alerts(self):
        from app.services.corporate_spending_alert_service import get_alerts_summary

        account = _make_account(monthly_budget_limit=None)
        admin_member = _make_member(user_id=1)
        db = AsyncMock()
        results = []
        r0 = MagicMock(); r0.scalar_one_or_none.return_value = account; results.append(r0)
        r1 = MagicMock(); r1.scalar_one_or_none.return_value = admin_member; results.append(r1)
        # _compute_account_spend
        r2 = MagicMock(); s2 = MagicMock(); s2.all.return_value = []; r2.scalars.return_value = s2; results.append(r2)
        # _get_active_members
        r3 = MagicMock(); s3 = MagicMock(); s3.all.return_value = []; r3.scalars.return_value = s3; results.append(r3)
        # _existing_alert_types for account
        r4 = MagicMock(); s4 = MagicMock(); s4.all.return_value = []; r4.scalars.return_value = s4; results.append(r4)
        db.execute = AsyncMock(side_effect=results)

        summary = await get_alerts_summary(db, account_id=1, requesting_user_id=1, year=YEAR, month=MONTH)
        assert summary.account_id == 1
        assert summary.account_alert is None
        assert summary.members_near_limit == []
        assert summary.members_at_limit == []
        assert summary.members_over_limit == []

    @pytest.mark.asyncio
    async def test_non_admin_raises_403(self):
        from app.services.corporate_spending_alert_service import get_alerts_summary
        from fastapi import HTTPException

        account = _make_account()
        db = AsyncMock()
        results = []
        r0 = MagicMock(); r0.scalar_one_or_none.return_value = account; results.append(r0)
        r1 = MagicMock(); r1.scalar_one_or_none.return_value = None; results.append(r1)
        db.execute = AsyncMock(side_effect=results)

        with pytest.raises(HTTPException) as exc_info:
            await get_alerts_summary(db, account_id=1, requesting_user_id=99, year=YEAR, month=MONTH)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_account_not_found_raises_404(self):
        from app.services.corporate_spending_alert_service import get_alerts_summary
        from fastapi import HTTPException

        db = AsyncMock()
        r0 = MagicMock(); r0.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(side_effect=[r0])

        with pytest.raises(HTTPException) as exc_info:
            await get_alerts_summary(db, account_id=999, requesting_user_id=1)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_account_pct_used_computed(self):
        from app.services.corporate_spending_alert_service import get_alerts_summary

        account = _make_account(monthly_budget_limit=Decimal("1000.00"))
        admin_member = _make_member(user_id=1)
        invoice = _make_invoice(total_amount=Decimal("500.00"))
        db = AsyncMock()
        results = []
        r0 = MagicMock(); r0.scalar_one_or_none.return_value = account; results.append(r0)
        r1 = MagicMock(); r1.scalar_one_or_none.return_value = admin_member; results.append(r1)
        r2 = MagicMock(); s2 = MagicMock(); s2.all.return_value = [invoice]; r2.scalars.return_value = s2; results.append(r2)
        r3 = MagicMock(); s3 = MagicMock(); s3.all.return_value = []; r3.scalars.return_value = s3; results.append(r3)
        r4 = MagicMock(); s4 = MagicMock(); s4.all.return_value = []; r4.scalars.return_value = s4; results.append(r4)
        db.execute = AsyncMock(side_effect=results)

        summary = await get_alerts_summary(db, account_id=1, requesting_user_id=1, year=YEAR, month=MONTH)
        assert summary.account_pct_used == 50.0
        assert summary.account_spend_usd == Decimal("500.00")

    @pytest.mark.asyncio
    async def test_member_near_limit_bucketed_correctly(self):
        from app.services.corporate_spending_alert_service import get_alerts_summary

        account = _make_account(monthly_budget_limit=None)
        admin_member = _make_member(member_id=10, user_id=1, monthly_spend_limit=Decimal("100.00"))
        # Spend = 80 / 1 member = 80, 80% of 100 = near (75-89%)
        invoice = _make_invoice(total_amount=Decimal("80.00"))
        db = AsyncMock()
        results = []
        r0 = MagicMock(); r0.scalar_one_or_none.return_value = account; results.append(r0)
        r1 = MagicMock(); r1.scalar_one_or_none.return_value = admin_member; results.append(r1)
        r2 = MagicMock(); s2 = MagicMock(); s2.all.return_value = [invoice]; r2.scalars.return_value = s2; results.append(r2)
        r3 = MagicMock(); s3 = MagicMock(); s3.all.return_value = [admin_member]; r3.scalars.return_value = s3; results.append(r3)
        r4 = MagicMock(); s4 = MagicMock(); s4.all.return_value = []; r4.scalars.return_value = s4; results.append(r4)
        # existing alerts for member
        r5 = MagicMock(); s5 = MagicMock(); s5.all.return_value = []; r5.scalars.return_value = s5; results.append(r5)
        db.execute = AsyncMock(side_effect=results)

        summary = await get_alerts_summary(db, account_id=1, requesting_user_id=1, year=YEAR, month=MONTH)
        assert len(summary.members_near_limit) == 1
        assert summary.members_near_limit[0].member_id == 10

    @pytest.mark.asyncio
    async def test_defaults_to_current_year_month(self):
        """year=None, month=None default to today's period."""
        from app.services.corporate_spending_alert_service import get_alerts_summary

        account = _make_account(monthly_budget_limit=None)
        admin_member = _make_member(user_id=1)
        db = AsyncMock()
        results = []
        r0 = MagicMock(); r0.scalar_one_or_none.return_value = account; results.append(r0)
        r1 = MagicMock(); r1.scalar_one_or_none.return_value = admin_member; results.append(r1)
        r2 = MagicMock(); s2 = MagicMock(); s2.all.return_value = []; r2.scalars.return_value = s2; results.append(r2)
        r3 = MagicMock(); s3 = MagicMock(); s3.all.return_value = []; r3.scalars.return_value = s3; results.append(r3)
        r4 = MagicMock(); s4 = MagicMock(); s4.all.return_value = []; r4.scalars.return_value = s4; results.append(r4)
        db.execute = AsyncMock(side_effect=results)

        with patch("app.services.corporate_spending_alert_service.date") as mock_date:
            mock_date.today.return_value = TODAY
            summary = await get_alerts_summary(db, account_id=1, requesting_user_id=1)
        assert summary.period_year == TODAY.year
        assert summary.period_month == TODAY.month


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


class TestTriggerAlertCheckEndpoint:
    """Tests for POST /corporate/{account_id}/spending-alerts/check."""

    @pytest.mark.asyncio
    async def test_201_with_new_alerts(self):
        from app.api.v1.corporate_spending_alerts import trigger_alert_check

        user = MagicMock(); user.id = 1
        db = AsyncMock()
        alert = _make_alert()

        with patch(
            "app.api.v1.corporate_spending_alerts.check_and_create_alerts",
            new_callable=AsyncMock,
            return_value=[alert],
        ) as mock_svc:
            result = await trigger_alert_check(
                account_id=1, as_of=None, db=db, current_user=user
            )
            mock_svc.assert_awaited_once_with(db, account_id=1, as_of_date=None)

        assert result.total == 1
        assert len(result.alerts) == 1

    @pytest.mark.asyncio
    async def test_201_with_empty_when_no_new_alerts(self):
        from app.api.v1.corporate_spending_alerts import trigger_alert_check

        user = MagicMock(); user.id = 1
        db = AsyncMock()

        with patch(
            "app.api.v1.corporate_spending_alerts.check_and_create_alerts",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await trigger_alert_check(
                account_id=1, as_of=None, db=db, current_user=user
            )

        assert result.total == 0
        assert result.alerts == []

    @pytest.mark.asyncio
    async def test_as_of_forwarded_to_service(self):
        from app.api.v1.corporate_spending_alerts import trigger_alert_check

        user = MagicMock(); user.id = 1
        db = AsyncMock()
        custom_date = date(2026, 3, 15)

        with patch(
            "app.api.v1.corporate_spending_alerts.check_and_create_alerts",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_svc:
            await trigger_alert_check(
                account_id=1, as_of=custom_date, db=db, current_user=user
            )
            mock_svc.assert_awaited_once_with(db, account_id=1, as_of_date=custom_date)

    @pytest.mark.asyncio
    async def test_404_propagated_from_service(self):
        from app.api.v1.corporate_spending_alerts import trigger_alert_check
        from fastapi import HTTPException

        user = MagicMock(); user.id = 1
        db = AsyncMock()

        with patch(
            "app.api.v1.corporate_spending_alerts.check_and_create_alerts",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=404, detail="Not found."),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await trigger_alert_check(account_id=999, as_of=None, db=db, current_user=user)
        assert exc_info.value.status_code == 404


class TestListAccountAlertsEndpoint:
    """Tests for GET /corporate/{account_id}/spending-alerts."""

    @pytest.mark.asyncio
    async def test_returns_alert_list(self):
        from app.api.v1.corporate_spending_alerts import list_account_alerts

        user = MagicMock(); user.id = 1
        db = AsyncMock()
        alert = _make_alert()

        with patch(
            "app.api.v1.corporate_spending_alerts.get_account_alerts",
            new_callable=AsyncMock,
            return_value=[alert],
        ):
            result = await list_account_alerts(
                account_id=1, year=YEAR, month=MONTH, db=db, current_user=user
            )

        assert result.total == 1

    @pytest.mark.asyncio
    async def test_defaults_to_current_period(self):
        from app.api.v1.corporate_spending_alerts import list_account_alerts

        user = MagicMock(); user.id = 1
        db = AsyncMock()

        with patch(
            "app.api.v1.corporate_spending_alerts.get_account_alerts",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_svc, patch(
            "app.api.v1.corporate_spending_alerts.date"
        ) as mock_date:
            mock_date.today.return_value = TODAY
            await list_account_alerts(
                account_id=1, year=None, month=None, db=db, current_user=user
            )
            mock_svc.assert_awaited_once_with(
                db,
                account_id=1,
                requesting_user_id=1,
                year=TODAY.year,
                month=TODAY.month,
            )

    @pytest.mark.asyncio
    async def test_403_non_admin(self):
        from app.api.v1.corporate_spending_alerts import list_account_alerts
        from fastapi import HTTPException

        user = MagicMock(); user.id = 99
        db = AsyncMock()

        with patch(
            "app.api.v1.corporate_spending_alerts.get_account_alerts",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=403, detail="Forbidden."),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await list_account_alerts(
                    account_id=1, year=YEAR, month=MONTH, db=db, current_user=user
                )
        assert exc_info.value.status_code == 403


class TestAccountAlertsSummaryEndpoint:
    """Tests for GET /corporate/{account_id}/spending-alerts/summary."""

    @pytest.mark.asyncio
    async def test_returns_summary(self):
        from app.api.v1.corporate_spending_alerts import account_alerts_summary

        user = MagicMock(); user.id = 1
        db = AsyncMock()
        mock_summary = SpendingAlertsSummary(
            account_id=1,
            period_year=YEAR,
            period_month=MONTH,
            account_spend_usd=Decimal("500.00"),
            account_limit_usd=Decimal("1000.00"),
            account_pct_used=50.0,
            account_alert=None,
            members_near_limit=[],
            members_at_limit=[],
            members_over_limit=[],
        )

        with patch(
            "app.api.v1.corporate_spending_alerts.get_alerts_summary",
            new_callable=AsyncMock,
            return_value=mock_summary,
        ) as mock_svc:
            result = await account_alerts_summary(
                account_id=1, year=YEAR, month=MONTH, db=db, current_user=user
            )
            mock_svc.assert_awaited_once_with(
                db, account_id=1, requesting_user_id=1, year=YEAR, month=MONTH
            )

        assert result.account_id == 1
        assert result.account_pct_used == 50.0

    @pytest.mark.asyncio
    async def test_403_non_admin(self):
        from app.api.v1.corporate_spending_alerts import account_alerts_summary
        from fastapi import HTTPException

        user = MagicMock(); user.id = 99
        db = AsyncMock()

        with patch(
            "app.api.v1.corporate_spending_alerts.get_alerts_summary",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=403, detail="Forbidden."),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await account_alerts_summary(
                    account_id=1, year=None, month=None, db=db, current_user=user
                )
        assert exc_info.value.status_code == 403


class TestListMyAlertsEndpoint:
    """Tests for GET /corporate/{account_id}/spending-alerts/my."""

    @pytest.mark.asyncio
    async def test_returns_own_alerts(self):
        from app.api.v1.corporate_spending_alerts import list_my_alerts

        user = MagicMock(); user.id = 1
        db = AsyncMock()
        alert = _make_alert(member_id=10)

        with patch(
            "app.api.v1.corporate_spending_alerts.get_member_alerts",
            new_callable=AsyncMock,
            return_value=[alert],
        ) as mock_svc:
            result = await list_my_alerts(
                account_id=1, member_id=10, year=YEAR, month=MONTH, db=db, current_user=user
            )
            mock_svc.assert_awaited_once_with(
                db,
                account_id=1,
                member_id=10,
                requesting_user_id=1,
                year=YEAR,
                month=MONTH,
            )

        assert result.total == 1

    @pytest.mark.asyncio
    async def test_403_wrong_member(self):
        from app.api.v1.corporate_spending_alerts import list_my_alerts
        from fastapi import HTTPException

        user = MagicMock(); user.id = 1
        db = AsyncMock()

        with patch(
            "app.api.v1.corporate_spending_alerts.get_member_alerts",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=403, detail="Forbidden."),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await list_my_alerts(
                    account_id=1, member_id=20, year=YEAR, month=MONTH, db=db, current_user=user
                )
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_defaults_to_current_period(self):
        from app.api.v1.corporate_spending_alerts import list_my_alerts

        user = MagicMock(); user.id = 1
        db = AsyncMock()

        with patch(
            "app.api.v1.corporate_spending_alerts.get_member_alerts",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_svc, patch(
            "app.api.v1.corporate_spending_alerts.date"
        ) as mock_date:
            mock_date.today.return_value = TODAY
            await list_my_alerts(
                account_id=1, member_id=10, year=None, month=None, db=db, current_user=user
            )
            mock_svc.assert_awaited_once_with(
                db,
                account_id=1,
                member_id=10,
                requesting_user_id=1,
                year=TODAY.year,
                month=TODAY.month,
            )


class TestAdminListAllSpendingAlertsEndpoint:
    """Tests for GET /admin/corporate/spending-alerts."""

    @pytest.mark.asyncio
    async def test_returns_list_of_summaries(self):
        from app.api.v1.corporate_spending_alerts import admin_list_all_spending_alerts

        db = AsyncMock()

        # The endpoint queries for distinct account_ids then builds a summary per account.
        # With no account IDs returned the result list should be empty.
        r0 = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        r0.scalars.return_value = scalars_mock
        db.execute = AsyncMock(side_effect=[r0])

        result = await admin_list_all_spending_alerts(year=YEAR, month=MONTH, db=db)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_alerts_exist(self):
        from app.api.v1.corporate_spending_alerts import admin_list_all_spending_alerts

        db = AsyncMock()
        r0 = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        r0.scalars.return_value = scalars_mock
        db.execute = AsyncMock(side_effect=[r0])

        result = await admin_list_all_spending_alerts(year=YEAR, month=MONTH, db=db)
        assert result == []

    @pytest.mark.asyncio
    async def test_defaults_to_current_period(self):
        from app.api.v1.corporate_spending_alerts import admin_list_all_spending_alerts

        db = AsyncMock()
        r0 = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        r0.scalars.return_value = scalars_mock
        db.execute = AsyncMock(side_effect=[r0])

        with patch("app.api.v1.corporate_spending_alerts.date") as mock_date:
            mock_date.today.return_value = TODAY
            result = await admin_list_all_spending_alerts(year=None, month=None, db=db)
        # No errors — defaults resolved to today's year/month
        assert isinstance(result, list)
