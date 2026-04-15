"""Tests for the Corporate Account Dashboard feature.

Service tests (async, mocked DB):
  1.  get_account_dashboard — 404 when account not found
  2.  get_account_dashboard — returns full dashboard when account exists
  3.  get_account_dashboard — credit section is None when no credit account
  4.  get_account_dashboard — credit section populated when credit account exists
  5.  get_account_dashboard — is_low_balance True when balance ≤ threshold
  6.  get_account_dashboard — is_low_balance False when balance > threshold
  7.  get_account_dashboard — budget_utilization_pct computed correctly
  8.  get_account_dashboard — budget_utilization_pct is None when no budget limit
  9.  get_account_dashboard — sso_configured False when no SSO config
  10. get_account_dashboard — sso_configured True with correct status when SSO present
  11. get_account_dashboard — sso_enforced True when enforce_sso is True
  12. get_account_dashboard — generated_at is recent UTC timestamp
  13. get_account_dashboard — pending sections match counts from DB
  14. get_account_dashboard — zero counts handled correctly

Schema tests (sync):
  15. AccountOverview — constructs from dict
  16. MembersSummary — constructs correctly
  17. SpendSummary — budget_utilization_pct accepts None
  18. CreditSummary — constructs correctly
  19. PendingItems — constructs correctly
  20. SetupHealth — constructs correctly
  21. AlertsSummary — constructs correctly
  22. BlackoutsSummary — constructs correctly
  23. CorporateAccountDashboard — constructs from full dict
  24. CorporateAccountDashboard — credit field accepts None

API layer tests (service patched):
  25. GET /corporate/{account_id}/dashboard — 200 with auth
  26. GET /corporate/{account_id}/dashboard — 404 propagated
  27. GET /corporate/{account_id}/dashboard — 401/403 without auth
  28. GET /platform-admin/corporate/{account_id}/dashboard — 200 for admin
  29. GET /platform-admin/corporate/{account_id}/dashboard — 403 for non-admin
  30. Dashboard response shape matches expected keys
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.schemas.corporate_account_dashboard import (
    AccountOverview,
    AlertsSummary,
    BlackoutsSummary,
    CorporateAccountDashboard,
    CreditSummary,
    MembersSummary,
    PendingItems,
    SetupHealth,
    SpendSummary,
)
from app.services.corporate_account_dashboard import get_account_dashboard

# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
_ACCOUNT_ID = 99


def _make_account(
    id: int = _ACCOUNT_ID,
    name: str = "Acme Corp",
    status=None,
    billing_email: str = "billing@acme.example",
    tax_id: str | None = None,
    monthly_budget_limit=None,
    created_at: datetime = _NOW,
):
    acct = MagicMock()
    acct.id = id
    acct.name = name
    acct.status = MagicMock()
    acct.status.value = "active"
    acct.billing_email = billing_email
    acct.tax_id = tax_id
    acct.monthly_budget_limit = monthly_budget_limit
    acct.created_at = created_at
    return acct


def _make_sso_config(status_value: str = "active", enforce_sso: bool = False):
    cfg = MagicMock()
    cfg.status = MagicMock()
    cfg.status.value = status_value
    cfg.enforce_sso = enforce_sso
    return cfg


def _make_credit_account(
    balance: Decimal = Decimal("500.00"),
    deposited: Decimal = Decimal("1000.00"),
    spent: Decimal = Decimal("500.00"),
    threshold: Decimal | None = None,
):
    ca = MagicMock()
    ca.balance_usd = balance
    ca.total_deposited_usd = deposited
    ca.total_spent_usd = spent
    ca.low_balance_threshold_usd = threshold
    return ca


def _make_full_dashboard_result(
    account=None,
    active_members: int = 5,
    admin_members: int = 2,
    pending_invitations: int = 1,
    pending_approvals: int = 0,
    sso_config=None,
    active_webhooks: int = 2,
    active_api_keys: int = 3,
    billing_contacts: int = 1,
    account_contacts: int = 2,
    notification_configs: int = 8,
    active_blackouts: int = 0,
    active_alerts: int = 3,
    triggered_alerts: int = 1,
    credit_account=None,
    rides_this_month: int = 42,
    spend_this_month: Decimal = Decimal("380.00"),
) -> tuple:
    return (
        active_members,
        admin_members,
        pending_invitations,
        pending_approvals,
        sso_config,
        active_webhooks,
        active_api_keys,
        billing_contacts,
        account_contacts,
        notification_configs,
        active_blackouts,
        active_alerts,
        triggered_alerts,
        credit_account,
        rides_this_month,
        spend_this_month,
    )


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_account_dashboard_404_when_account_missing():
    """get_account_dashboard raises 404 when the account does not exist."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result

    with pytest.raises(HTTPException) as exc_info:
        await get_account_dashboard(db, account_id=999)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_account_dashboard_returns_full_structure():
    """get_account_dashboard returns a dict with all required keys."""
    account = _make_account()
    sub_query_result = _make_full_dashboard_result()

    with (
        patch(
            "app.services.corporate_account_dashboard._get_account_or_404",
            new=AsyncMock(return_value=account),
        ),
        patch(
            "app.services.corporate_account_dashboard._run_sub_queries",
            new=AsyncMock(return_value=sub_query_result),
        ),
    ):
        db = AsyncMock()
        result = await get_account_dashboard(db, account_id=_ACCOUNT_ID)

    assert "account" in result
    assert "members" in result
    assert "spend" in result
    assert "credit" in result
    assert "pending" in result
    assert "setup" in result
    assert "alerts" in result
    assert "blackouts" in result
    assert "generated_at" in result


@pytest.mark.asyncio
async def test_get_account_dashboard_credit_none_when_no_credit_account():
    """credit section is None when no CorporateCreditAccount exists."""
    account = _make_account()
    sub_query_result = _make_full_dashboard_result(credit_account=None)

    with (
        patch(
            "app.services.corporate_account_dashboard._get_account_or_404",
            new=AsyncMock(return_value=account),
        ),
        patch(
            "app.services.corporate_account_dashboard._run_sub_queries",
            new=AsyncMock(return_value=sub_query_result),
        ),
    ):
        db = AsyncMock()
        result = await get_account_dashboard(db, account_id=_ACCOUNT_ID)

    assert result["credit"] is None


@pytest.mark.asyncio
async def test_get_account_dashboard_credit_populated_when_exists():
    """credit section contains balance details when a credit account exists."""
    account = _make_account()
    credit = _make_credit_account(
        balance=Decimal("250.00"),
        deposited=Decimal("1000.00"),
        spent=Decimal("750.00"),
    )
    sub_query_result = _make_full_dashboard_result(credit_account=credit)

    with (
        patch(
            "app.services.corporate_account_dashboard._get_account_or_404",
            new=AsyncMock(return_value=account),
        ),
        patch(
            "app.services.corporate_account_dashboard._run_sub_queries",
            new=AsyncMock(return_value=sub_query_result),
        ),
    ):
        db = AsyncMock()
        result = await get_account_dashboard(db, account_id=_ACCOUNT_ID)

    assert result["credit"]["balance_usd"] == Decimal("250.00")
    assert result["credit"]["total_deposited_usd"] == Decimal("1000.00")
    assert result["credit"]["total_spent_usd"] == Decimal("750.00")


@pytest.mark.asyncio
async def test_get_account_dashboard_is_low_balance_true():
    """is_low_balance is True when balance ≤ threshold."""
    account = _make_account()
    credit = _make_credit_account(
        balance=Decimal("50.00"), threshold=Decimal("100.00")
    )
    sub_query_result = _make_full_dashboard_result(credit_account=credit)

    with (
        patch(
            "app.services.corporate_account_dashboard._get_account_or_404",
            new=AsyncMock(return_value=account),
        ),
        patch(
            "app.services.corporate_account_dashboard._run_sub_queries",
            new=AsyncMock(return_value=sub_query_result),
        ),
    ):
        db = AsyncMock()
        result = await get_account_dashboard(db, account_id=_ACCOUNT_ID)

    assert result["credit"]["is_low_balance"] is True


@pytest.mark.asyncio
async def test_get_account_dashboard_is_low_balance_false():
    """is_low_balance is False when balance > threshold."""
    account = _make_account()
    credit = _make_credit_account(
        balance=Decimal("500.00"), threshold=Decimal("100.00")
    )
    sub_query_result = _make_full_dashboard_result(credit_account=credit)

    with (
        patch(
            "app.services.corporate_account_dashboard._get_account_or_404",
            new=AsyncMock(return_value=account),
        ),
        patch(
            "app.services.corporate_account_dashboard._run_sub_queries",
            new=AsyncMock(return_value=sub_query_result),
        ),
    ):
        db = AsyncMock()
        result = await get_account_dashboard(db, account_id=_ACCOUNT_ID)

    assert result["credit"]["is_low_balance"] is False


@pytest.mark.asyncio
async def test_get_account_dashboard_budget_utilization_computed():
    """budget_utilization_pct is computed as spend / budget × 100."""
    account = _make_account(monthly_budget_limit=Decimal("1000.00"))
    sub_query_result = _make_full_dashboard_result(
        spend_this_month=Decimal("250.00")
    )

    with (
        patch(
            "app.services.corporate_account_dashboard._get_account_or_404",
            new=AsyncMock(return_value=account),
        ),
        patch(
            "app.services.corporate_account_dashboard._run_sub_queries",
            new=AsyncMock(return_value=sub_query_result),
        ),
    ):
        db = AsyncMock()
        result = await get_account_dashboard(db, account_id=_ACCOUNT_ID)

    assert result["spend"]["budget_utilization_pct"] == 25.0


@pytest.mark.asyncio
async def test_get_account_dashboard_budget_utilization_none_when_no_limit():
    """budget_utilization_pct is None when monthly_budget_limit is None."""
    account = _make_account(monthly_budget_limit=None)
    sub_query_result = _make_full_dashboard_result(spend_this_month=Decimal("500.00"))

    with (
        patch(
            "app.services.corporate_account_dashboard._get_account_or_404",
            new=AsyncMock(return_value=account),
        ),
        patch(
            "app.services.corporate_account_dashboard._run_sub_queries",
            new=AsyncMock(return_value=sub_query_result),
        ),
    ):
        db = AsyncMock()
        result = await get_account_dashboard(db, account_id=_ACCOUNT_ID)

    assert result["spend"]["budget_utilization_pct"] is None


@pytest.mark.asyncio
async def test_get_account_dashboard_sso_not_configured():
    """sso_configured is False and sso_status is None when no SSO config exists."""
    account = _make_account()
    sub_query_result = _make_full_dashboard_result(sso_config=None)

    with (
        patch(
            "app.services.corporate_account_dashboard._get_account_or_404",
            new=AsyncMock(return_value=account),
        ),
        patch(
            "app.services.corporate_account_dashboard._run_sub_queries",
            new=AsyncMock(return_value=sub_query_result),
        ),
    ):
        db = AsyncMock()
        result = await get_account_dashboard(db, account_id=_ACCOUNT_ID)

    assert result["setup"]["sso_configured"] is False
    assert result["setup"]["sso_status"] is None
    assert result["setup"]["sso_enforced"] is False


@pytest.mark.asyncio
async def test_get_account_dashboard_sso_configured_with_status():
    """sso_configured is True with correct status when SSO config exists."""
    account = _make_account()
    sso = _make_sso_config(status_value="active", enforce_sso=False)
    sub_query_result = _make_full_dashboard_result(sso_config=sso)

    with (
        patch(
            "app.services.corporate_account_dashboard._get_account_or_404",
            new=AsyncMock(return_value=account),
        ),
        patch(
            "app.services.corporate_account_dashboard._run_sub_queries",
            new=AsyncMock(return_value=sub_query_result),
        ),
    ):
        db = AsyncMock()
        result = await get_account_dashboard(db, account_id=_ACCOUNT_ID)

    assert result["setup"]["sso_configured"] is True
    assert result["setup"]["sso_status"] == "active"
    assert result["setup"]["sso_enforced"] is False


@pytest.mark.asyncio
async def test_get_account_dashboard_sso_enforced_true():
    """sso_enforced is True when enforce_sso is True on the SSO config."""
    account = _make_account()
    sso = _make_sso_config(status_value="active", enforce_sso=True)
    sub_query_result = _make_full_dashboard_result(sso_config=sso)

    with (
        patch(
            "app.services.corporate_account_dashboard._get_account_or_404",
            new=AsyncMock(return_value=account),
        ),
        patch(
            "app.services.corporate_account_dashboard._run_sub_queries",
            new=AsyncMock(return_value=sub_query_result),
        ),
    ):
        db = AsyncMock()
        result = await get_account_dashboard(db, account_id=_ACCOUNT_ID)

    assert result["setup"]["sso_enforced"] is True


@pytest.mark.asyncio
async def test_get_account_dashboard_generated_at_is_recent():
    """generated_at is a recent UTC datetime."""
    account = _make_account()
    sub_query_result = _make_full_dashboard_result()

    before = datetime.now(tz=timezone.utc)

    with (
        patch(
            "app.services.corporate_account_dashboard._get_account_or_404",
            new=AsyncMock(return_value=account),
        ),
        patch(
            "app.services.corporate_account_dashboard._run_sub_queries",
            new=AsyncMock(return_value=sub_query_result),
        ),
    ):
        db = AsyncMock()
        result = await get_account_dashboard(db, account_id=_ACCOUNT_ID)

    after = datetime.now(tz=timezone.utc)
    assert before <= result["generated_at"] <= after


@pytest.mark.asyncio
async def test_get_account_dashboard_pending_section_correct():
    """pending section reflects counts from sub-queries."""
    account = _make_account()
    sub_query_result = _make_full_dashboard_result(
        pending_invitations=3, pending_approvals=7
    )

    with (
        patch(
            "app.services.corporate_account_dashboard._get_account_or_404",
            new=AsyncMock(return_value=account),
        ),
        patch(
            "app.services.corporate_account_dashboard._run_sub_queries",
            new=AsyncMock(return_value=sub_query_result),
        ),
    ):
        db = AsyncMock()
        result = await get_account_dashboard(db, account_id=_ACCOUNT_ID)

    assert result["pending"]["pending_invitations"] == 3
    assert result["pending"]["pending_ride_approvals"] == 7


@pytest.mark.asyncio
async def test_get_account_dashboard_zero_counts():
    """Zero counts are returned correctly (no None / missing keys)."""
    account = _make_account()
    sub_query_result = _make_full_dashboard_result(
        active_members=0,
        admin_members=0,
        pending_invitations=0,
        pending_approvals=0,
        active_webhooks=0,
        active_api_keys=0,
        billing_contacts=0,
        account_contacts=0,
        notification_configs=0,
        active_blackouts=0,
        active_alerts=0,
        triggered_alerts=0,
        rides_this_month=0,
        spend_this_month=Decimal("0.00"),
    )

    with (
        patch(
            "app.services.corporate_account_dashboard._get_account_or_404",
            new=AsyncMock(return_value=account),
        ),
        patch(
            "app.services.corporate_account_dashboard._run_sub_queries",
            new=AsyncMock(return_value=sub_query_result),
        ),
    ):
        db = AsyncMock()
        result = await get_account_dashboard(db, account_id=_ACCOUNT_ID)

    assert result["members"]["total_active"] == 0
    assert result["spend"]["rides_this_month"] == 0
    assert result["spend"]["spend_this_month_usd"] == Decimal("0.00")
    assert result["alerts"]["total_active"] == 0
    assert result["alerts"]["total_triggered"] == 0


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_account_overview_from_dict():
    """AccountOverview constructs from a plain dict."""
    data = {
        "id": 1,
        "name": "Acme",
        "status": "active",
        "billing_email": "b@acme.example",
        "tax_id": None,
        "monthly_budget_limit": None,
        "created_at": _NOW,
    }
    overview = AccountOverview(**data)
    assert overview.id == 1
    assert overview.name == "Acme"
    assert overview.status == "active"


def test_members_summary_constructs():
    """MembersSummary constructs correctly."""
    m = MembersSummary(total_active=10, total_admins=2, pending_invitations=1)
    assert m.total_active == 10
    assert m.total_admins == 2
    assert m.pending_invitations == 1


def test_spend_summary_accepts_none_utilization():
    """SpendSummary accepts None for budget_utilization_pct."""
    s = SpendSummary(
        rides_this_month=5,
        spend_this_month_usd=Decimal("100.00"),
        monthly_budget_limit=None,
        budget_utilization_pct=None,
    )
    assert s.budget_utilization_pct is None


def test_credit_summary_constructs():
    """CreditSummary constructs correctly."""
    c = CreditSummary(
        balance_usd=Decimal("300.00"),
        total_deposited_usd=Decimal("1000.00"),
        total_spent_usd=Decimal("700.00"),
        low_balance_threshold_usd=Decimal("100.00"),
        is_low_balance=False,
    )
    assert c.balance_usd == Decimal("300.00")
    assert c.is_low_balance is False


def test_pending_items_constructs():
    """PendingItems constructs correctly."""
    p = PendingItems(pending_ride_approvals=3, pending_invitations=1)
    assert p.pending_ride_approvals == 3


def test_setup_health_constructs():
    """SetupHealth constructs with all fields."""
    s = SetupHealth(
        sso_configured=True,
        sso_status="active",
        sso_enforced=True,
        active_webhooks=2,
        active_api_keys=3,
        billing_contacts=1,
        account_contacts=2,
        notification_configs=12,
    )
    assert s.sso_configured is True
    assert s.notification_configs == 12


def test_alerts_summary_constructs():
    """AlertsSummary constructs correctly."""
    a = AlertsSummary(total_active=5, total_triggered=2)
    assert a.total_triggered == 2


def test_blackouts_summary_constructs():
    """BlackoutsSummary constructs correctly."""
    b = BlackoutsSummary(total_active=1)
    assert b.total_active == 1


def _full_dashboard_dict() -> dict:
    return {
        "account": {
            "id": _ACCOUNT_ID,
            "name": "Acme Corp",
            "status": "active",
            "billing_email": "b@acme.example",
            "tax_id": None,
            "monthly_budget_limit": None,
            "created_at": _NOW,
        },
        "members": {"total_active": 5, "total_admins": 2, "pending_invitations": 1},
        "spend": {
            "rides_this_month": 10,
            "spend_this_month_usd": Decimal("200.00"),
            "monthly_budget_limit": None,
            "budget_utilization_pct": None,
        },
        "credit": None,
        "pending": {"pending_ride_approvals": 0, "pending_invitations": 1},
        "setup": {
            "sso_configured": False,
            "sso_status": None,
            "sso_enforced": False,
            "active_webhooks": 1,
            "active_api_keys": 2,
            "billing_contacts": 1,
            "account_contacts": 2,
            "notification_configs": 8,
        },
        "alerts": {"total_active": 3, "total_triggered": 0},
        "blackouts": {"total_active": 0},
        "generated_at": _NOW,
    }


def test_corporate_account_dashboard_constructs():
    """CorporateAccountDashboard constructs from a full dict."""
    dashboard = CorporateAccountDashboard(**_full_dashboard_dict())
    assert dashboard.account.name == "Acme Corp"
    assert dashboard.members.total_active == 5
    assert dashboard.credit is None


def test_corporate_account_dashboard_credit_field_accepts_none():
    """CorporateAccountDashboard accepts credit=None."""
    data = _full_dashboard_dict()
    data["credit"] = None
    dashboard = CorporateAccountDashboard(**data)
    assert dashboard.credit is None


# ---------------------------------------------------------------------------
# API layer tests
# ---------------------------------------------------------------------------

_DUMMY_DASHBOARD = _full_dashboard_dict()


def _make_app_client(is_admin: bool = False):
    """Build a TestClient with auth + DB deps overridden."""
    from app.main import app
    from app.api.deps import get_current_user, get_db, require_admin
    from app.models.user import User

    mock_user = MagicMock(spec=User)
    mock_user.id = 1
    role = MagicMock()
    role.value = "admin" if is_admin else "rider"
    mock_user.role = role

    async def override_user():
        return mock_user

    async def override_admin():
        if not is_admin:
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Admin access required")
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


@patch(
    "app.api.v1.corporate_account_dashboard.get_account_dashboard",
    new_callable=AsyncMock,
    return_value=_DUMMY_DASHBOARD,
)
def test_api_get_dashboard_200(mock_svc):
    """GET /corporate/{account_id}/dashboard returns 200 for authenticated user."""
    client = _make_app_client()
    response = client.get(f"/api/v1/corporate/{_ACCOUNT_ID}/dashboard")
    assert response.status_code == 200
    data = response.json()
    assert data["account"]["name"] == "Acme Corp"
    assert "members" in data
    assert "spend" in data


@patch(
    "app.api.v1.corporate_account_dashboard.get_account_dashboard",
    new_callable=AsyncMock,
    side_effect=HTTPException(status_code=404, detail="Corporate account 999 not found."),
)
def test_api_get_dashboard_404_propagated(mock_svc):
    """GET /corporate/{account_id}/dashboard returns 404 when service raises it."""
    client = _make_app_client()
    response = client.get("/api/v1/corporate/999/dashboard")
    assert response.status_code == 404


def test_api_get_dashboard_unauthenticated():
    """GET /corporate/{account_id}/dashboard returns 401/403 without auth."""
    from app.main import app
    client = TestClient(app, raise_server_exceptions=True)
    response = client.get(f"/api/v1/corporate/{_ACCOUNT_ID}/dashboard")
    assert response.status_code in (401, 403)


@patch(
    "app.api.v1.corporate_account_dashboard.get_account_dashboard",
    new_callable=AsyncMock,
    return_value=_DUMMY_DASHBOARD,
)
def test_api_platform_admin_dashboard_200(mock_svc):
    """GET /platform-admin/corporate/{account_id}/dashboard returns 200 for admin."""
    client = _make_app_client(is_admin=True)
    response = client.get(f"/api/v1/platform-admin/corporate/{_ACCOUNT_ID}/dashboard")
    assert response.status_code == 200
    data = response.json()
    assert "account" in data
    assert "setup" in data


def test_api_platform_admin_dashboard_403_for_non_admin():
    """GET /platform-admin/corporate/{account_id}/dashboard returns 403 for non-admin."""
    client = _make_app_client(is_admin=False)
    response = client.get(f"/api/v1/platform-admin/corporate/{_ACCOUNT_ID}/dashboard")
    assert response.status_code == 403


@patch(
    "app.api.v1.corporate_account_dashboard.get_account_dashboard",
    new_callable=AsyncMock,
    return_value=_DUMMY_DASHBOARD,
)
def test_api_dashboard_response_shape(mock_svc):
    """Dashboard response contains all expected top-level keys."""
    client = _make_app_client()
    response = client.get(f"/api/v1/corporate/{_ACCOUNT_ID}/dashboard")
    assert response.status_code == 200
    data = response.json()
    expected_keys = {
        "account", "members", "spend", "credit", "pending",
        "setup", "alerts", "blackouts", "generated_at",
    }
    assert expected_keys.issubset(data.keys())
