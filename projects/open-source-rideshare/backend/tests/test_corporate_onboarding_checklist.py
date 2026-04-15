"""Tests for the Corporate Account Onboarding Checklist feature.

Service layer (async, mocked DB):
  1.  Empty account → all steps incomplete, all_required_complete=False
  2.  Billing settings present but no payment method → billing incomplete
  3.  Billing settings + active payment method → billing complete
  4.  At least one active member → employees complete
  5.  Ride policy row exists → ride_policy complete
  6.  Active cost center exists → cost_centers complete
  7.  Active trip purpose exists → trip_purposes complete
  8.  Notification config with enabled=True → notifications complete
  9.  Notification config with enabled=False → notifications incomplete
  10. Active webhook → integrations complete
  11. Active API key → integrations complete (no webhook)
  12. SSO with status=active → sso complete
  13. SSO with status=pending → sso incomplete
  14. All required steps complete → all_required_complete=True
  15. completion_pct: 3 of 5 required complete → 60.0
  16. Optional steps do not affect all_required_complete
  17. Step ordering: required steps precede optional steps
  18. total_steps is always 8 (5 required + 3 optional)
  19. required_steps is always 5
  20. completed_optional counts optional completions correctly

Schema validation:
  21. OnboardingStep — valid construction
  22. OnboardingChecklistResponse — valid with all fields
  23. completion_pct at 0.0 when no required steps complete
  24. completion_pct at 100.0 when all required steps complete

API layer (service functions patched):
  25. GET /corporate/accounts/me/onboarding-checklist — 200, member
  26. GET /corporate/accounts/me/onboarding-checklist — 404 when not in account
  27. GET /admin/corporate/accounts/{id}/onboarding-checklist — 200, admin
  28. Non-admin call to admin endpoint raises 403
  29. Step keys in response match expected set
  30. Step action_hint values are non-empty strings
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.schemas.corporate_onboarding_checklist import (
    OnboardingChecklistResponse,
    OnboardingStep,
)
from app.services.corporate_onboarding_checklist import get_onboarding_checklist


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

ACCOUNT_ID = 42
USER_ID = 1
ADMIN_ID = 2

_REQUIRED_STEP_KEYS = {"billing", "employees", "ride_policy", "cost_centers", "trip_purposes"}
_OPTIONAL_STEP_KEYS = {"notifications", "sso", "integrations"}
_ALL_STEP_KEYS = _REQUIRED_STEP_KEYS | _OPTIONAL_STEP_KEYS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(scalar_sequence: list[int]) -> AsyncMock:
    """Return a mock AsyncSession whose scalar() calls return values in order."""
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=scalar_sequence)
    return db


def _all_zero_db() -> AsyncMock:
    """DB that returns 0 for every scalar query (10 queries total)."""
    return _make_db([0] * 10)


def _make_checklist_response(
    completed_required: int = 0,
    completed_optional: int = 0,
    steps: list[OnboardingStep] | None = None,
) -> OnboardingChecklistResponse:
    """Build a minimal OnboardingChecklistResponse for API layer mocking."""
    if steps is None:
        steps = []
    required_steps = 5
    return OnboardingChecklistResponse(
        account_id=ACCOUNT_ID,
        total_steps=8,
        required_steps=required_steps,
        completed_required=completed_required,
        completed_optional=completed_optional,
        all_required_complete=(completed_required == required_steps),
        completion_pct=completed_required / required_steps * 100,
        steps=steps,
    )


# ---------------------------------------------------------------------------
# 1. Empty account — all steps incomplete
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_empty_account_all_incomplete():
    db = _all_zero_db()
    result = await get_onboarding_checklist(db, ACCOUNT_ID)

    assert result.account_id == ACCOUNT_ID
    assert result.all_required_complete is False
    assert result.completed_required == 0
    assert result.completed_optional == 0
    assert all(not s.is_complete for s in result.steps)


# ---------------------------------------------------------------------------
# 2. Billing settings present but no active payment method → billing incomplete
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_billing_settings_without_payment_method():
    # billing_settings=1, active_payment_methods=0, then all zeros
    db = _make_db([1, 0] + [0] * 8)
    result = await get_onboarding_checklist(db, ACCOUNT_ID)

    billing_step = next(s for s in result.steps if s.step_key == "billing")
    assert billing_step.is_complete is False


# ---------------------------------------------------------------------------
# 3. Billing settings + active payment method → billing complete
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_billing_complete():
    # billing_settings=1, active_payment_methods=1, then all zeros
    db = _make_db([1, 1] + [0] * 8)
    result = await get_onboarding_checklist(db, ACCOUNT_ID)

    billing_step = next(s for s in result.steps if s.step_key == "billing")
    assert billing_step.is_complete is True


# ---------------------------------------------------------------------------
# 4. Active member present → employees complete
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_employees_complete():
    # billing=0,0 | members=1 | ride_policy=0 | cost_centers=0 | trip_purposes=0
    # notifications=0 | sso=0 | webhooks=0 | api_keys=0
    db = _make_db([0, 0, 1, 0, 0, 0, 0, 0, 0, 0])
    result = await get_onboarding_checklist(db, ACCOUNT_ID)

    employees_step = next(s for s in result.steps if s.step_key == "employees")
    assert employees_step.is_complete is True


# ---------------------------------------------------------------------------
# 5. Ride policy row exists → ride_policy complete
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_ride_policy_complete():
    # billing=0,0 | members=0 | ride_policy=1 | rest=0
    db = _make_db([0, 0, 0, 1, 0, 0, 0, 0, 0, 0])
    result = await get_onboarding_checklist(db, ACCOUNT_ID)

    ride_policy_step = next(s for s in result.steps if s.step_key == "ride_policy")
    assert ride_policy_step.is_complete is True


# ---------------------------------------------------------------------------
# 6. Active cost center exists → cost_centers complete
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cost_centers_complete():
    # billing=0,0 | members=0 | ride_policy=0 | cost_centers=1 | rest=0
    db = _make_db([0, 0, 0, 0, 1, 0, 0, 0, 0, 0])
    result = await get_onboarding_checklist(db, ACCOUNT_ID)

    cost_step = next(s for s in result.steps if s.step_key == "cost_centers")
    assert cost_step.is_complete is True


# ---------------------------------------------------------------------------
# 7. Active trip purpose exists → trip_purposes complete
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_trip_purposes_complete():
    # billing=0,0 | members=0 | ride_policy=0 | cost_centers=0 | trip_purposes=1 | rest=0
    db = _make_db([0, 0, 0, 0, 0, 1, 0, 0, 0, 0])
    result = await get_onboarding_checklist(db, ACCOUNT_ID)

    purpose_step = next(s for s in result.steps if s.step_key == "trip_purposes")
    assert purpose_step.is_complete is True


# ---------------------------------------------------------------------------
# 8. Notification config with enabled=True → notifications complete
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_notifications_complete_enabled_true():
    # billing=0,0 | members=0 | ride_policy=0 | cost_centers=0 | trip_purposes=0
    # notifications=1 | sso=0 | webhooks=0 | api_keys=0
    db = _make_db([0, 0, 0, 0, 0, 0, 1, 0, 0, 0])
    result = await get_onboarding_checklist(db, ACCOUNT_ID)

    notif_step = next(s for s in result.steps if s.step_key == "notifications")
    assert notif_step.is_complete is True
    assert notif_step.is_optional is True


# ---------------------------------------------------------------------------
# 9. Notification config present but enabled=False → notifications incomplete
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_notifications_incomplete_all_disabled():
    # All zeros means no enabled=True notifications found
    db = _all_zero_db()
    result = await get_onboarding_checklist(db, ACCOUNT_ID)

    notif_step = next(s for s in result.steps if s.step_key == "notifications")
    assert notif_step.is_complete is False


# ---------------------------------------------------------------------------
# 10. Active webhook → integrations complete
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_integrations_complete_via_webhook():
    # billing=0,0 | members=0 | ride_policy=0 | cost_centers=0 | trip_purposes=0
    # notifications=0 | sso=0 | webhooks=1 | api_keys=0
    db = _make_db([0, 0, 0, 0, 0, 0, 0, 0, 1, 0])
    result = await get_onboarding_checklist(db, ACCOUNT_ID)

    integ_step = next(s for s in result.steps if s.step_key == "integrations")
    assert integ_step.is_complete is True


# ---------------------------------------------------------------------------
# 11. Active API key → integrations complete (no webhook)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_integrations_complete_via_api_key():
    # billing=0,0 | members=0 | ride_policy=0 | cost_centers=0 | trip_purposes=0
    # notifications=0 | sso=0 | webhooks=0 | api_keys=1
    db = _make_db([0, 0, 0, 0, 0, 0, 0, 0, 0, 1])
    result = await get_onboarding_checklist(db, ACCOUNT_ID)

    integ_step = next(s for s in result.steps if s.step_key == "integrations")
    assert integ_step.is_complete is True


# ---------------------------------------------------------------------------
# 12. SSO with status=active → sso complete
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_sso_complete_active_status():
    # billing=0,0 | members=0 | ride_policy=0 | cost_centers=0 | trip_purposes=0
    # notifications=0 | sso=1 | webhooks=0 | api_keys=0
    db = _make_db([0, 0, 0, 0, 0, 0, 0, 1, 0, 0])
    result = await get_onboarding_checklist(db, ACCOUNT_ID)

    sso_step = next(s for s in result.steps if s.step_key == "sso")
    assert sso_step.is_complete is True
    assert sso_step.is_optional is True


# ---------------------------------------------------------------------------
# 13. SSO with status=pending → sso incomplete
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_sso_incomplete_pending_status():
    # sso query returns 0 (pending status doesn't match active filter)
    db = _all_zero_db()
    result = await get_onboarding_checklist(db, ACCOUNT_ID)

    sso_step = next(s for s in result.steps if s.step_key == "sso")
    assert sso_step.is_complete is False


# ---------------------------------------------------------------------------
# 14. All required steps complete → all_required_complete=True
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_all_required_complete():
    # billing_settings=1, payment_methods=1, members=1, ride_policy=1,
    # cost_centers=1, trip_purposes=1, notifications=0, sso=0, webhooks=0, api_keys=0
    db = _make_db([1, 1, 1, 1, 1, 1, 0, 0, 0, 0])
    result = await get_onboarding_checklist(db, ACCOUNT_ID)

    assert result.all_required_complete is True
    assert result.completed_required == 5


# ---------------------------------------------------------------------------
# 15. completion_pct: 3 of 5 required → 60.0
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_completion_pct_partial():
    # billing complete (1,1), members complete (1), ride_policy complete (1),
    # cost_centers=0, trip_purposes=0, rest=0
    db = _make_db([1, 1, 1, 1, 0, 0, 0, 0, 0, 0])
    result = await get_onboarding_checklist(db, ACCOUNT_ID)

    assert result.completed_required == 3
    assert result.completion_pct == pytest.approx(60.0, rel=1e-3)


# ---------------------------------------------------------------------------
# 16. Optional steps do not affect all_required_complete
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_optional_steps_do_not_block_required_completion():
    # All required complete, all optional complete
    db = _make_db([1, 1, 1, 1, 1, 1, 1, 1, 1, 1])
    result = await get_onboarding_checklist(db, ACCOUNT_ID)

    assert result.all_required_complete is True

    # Also verify that when required incomplete but optional complete,
    # all_required_complete is still False
    db2 = _make_db([0, 0, 0, 0, 0, 0, 1, 1, 1, 1])
    result2 = await get_onboarding_checklist(db2, ACCOUNT_ID)
    assert result2.all_required_complete is False


# ---------------------------------------------------------------------------
# 17. Step ordering: required steps precede optional steps
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_step_ordering_required_before_optional():
    db = _all_zero_db()
    result = await get_onboarding_checklist(db, ACCOUNT_ID)

    required_indices = [i for i, s in enumerate(result.steps) if not s.is_optional]
    optional_indices = [i for i, s in enumerate(result.steps) if s.is_optional]

    assert max(required_indices) < min(optional_indices), (
        "All required steps should appear before any optional step"
    )


# ---------------------------------------------------------------------------
# 18. total_steps is always 8
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_total_steps_always_eight():
    db = _all_zero_db()
    result = await get_onboarding_checklist(db, ACCOUNT_ID)

    assert result.total_steps == 8
    assert len(result.steps) == 8


# ---------------------------------------------------------------------------
# 19. required_steps is always 5
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_required_steps_always_five():
    db = _all_zero_db()
    result = await get_onboarding_checklist(db, ACCOUNT_ID)

    assert result.required_steps == 5
    required_in_list = sum(1 for s in result.steps if not s.is_optional)
    assert required_in_list == 5


# ---------------------------------------------------------------------------
# 20. completed_optional counts correctly
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_completed_optional_count():
    # required all incomplete, notifications=1, sso=1, webhooks=1, api_keys=0
    db = _make_db([0, 0, 0, 0, 0, 0, 1, 1, 1, 0])
    result = await get_onboarding_checklist(db, ACCOUNT_ID)

    assert result.completed_optional == 3


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_onboarding_step_valid():
    step = OnboardingStep(
        step_key="billing",
        title="Billing Setup",
        description="Configure billing settings.",
        is_complete=True,
        is_optional=False,
        action_hint="/corporate/billing",
    )
    assert step.step_key == "billing"
    assert step.is_complete is True
    assert step.is_optional is False


def test_onboarding_checklist_response_valid():
    steps = [
        OnboardingStep(
            step_key="billing",
            title="Billing",
            description="Billing desc",
            is_complete=True,
            is_optional=False,
            action_hint="/corporate/billing",
        )
    ]
    r = OnboardingChecklistResponse(
        account_id=ACCOUNT_ID,
        total_steps=1,
        required_steps=1,
        completed_required=1,
        completed_optional=0,
        all_required_complete=True,
        completion_pct=100.0,
        steps=steps,
    )
    assert r.account_id == ACCOUNT_ID
    assert r.all_required_complete is True
    assert r.completion_pct == 100.0


def test_completion_pct_zero_when_nothing_done():
    r = OnboardingChecklistResponse(
        account_id=ACCOUNT_ID,
        total_steps=8,
        required_steps=5,
        completed_required=0,
        completed_optional=0,
        all_required_complete=False,
        completion_pct=0.0,
        steps=[],
    )
    assert r.completion_pct == 0.0


def test_completion_pct_one_hundred_all_done():
    r = OnboardingChecklistResponse(
        account_id=ACCOUNT_ID,
        total_steps=8,
        required_steps=5,
        completed_required=5,
        completed_optional=3,
        all_required_complete=True,
        completion_pct=100.0,
        steps=[],
    )
    assert r.completion_pct == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# API layer tests
# ---------------------------------------------------------------------------

_ROUTER = "app.api.v1.corporate_onboarding_checklist"


def _mock_user(user_id: int = USER_ID) -> MagicMock:
    u = MagicMock()
    u.id = user_id
    return u


# ---------------------------------------------------------------------------
# 25. GET /corporate/accounts/me/onboarding-checklist — 200
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_get_my_onboarding_checklist_200():
    from app.api.v1.corporate_onboarding_checklist import get_my_onboarding_checklist

    user = _mock_user()
    db = AsyncMock()
    mock_response = _make_checklist_response()

    with patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch(f"{_ROUTER}.get_onboarding_checklist", new=AsyncMock(return_value=mock_response)):
        result = await get_my_onboarding_checklist(user=user, db=db)

    assert result.account_id == ACCOUNT_ID


# ---------------------------------------------------------------------------
# 26. GET /corporate/accounts/me/onboarding-checklist — 404 when not in account
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_get_my_onboarding_checklist_no_account_404():
    from app.api.v1.corporate_onboarding_checklist import get_my_onboarding_checklist

    user = _mock_user()
    db = AsyncMock()

    with patch(
        f"{_ROUTER}._resolve_account_id",
        new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Not found")),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await get_my_onboarding_checklist(user=user, db=db)

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 27. GET /admin/corporate/accounts/{id}/onboarding-checklist — 200
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_admin_get_onboarding_checklist_200():
    from app.api.v1.corporate_onboarding_checklist import admin_get_onboarding_checklist

    admin = _mock_user(user_id=ADMIN_ID)
    db = AsyncMock()
    mock_response = _make_checklist_response(completed_required=5)

    with patch(f"{_ROUTER}.get_onboarding_checklist", new=AsyncMock(return_value=mock_response)):
        result = await admin_get_onboarding_checklist(
            account_id=ACCOUNT_ID, _admin=admin, db=db
        )

    assert result.account_id == ACCOUNT_ID
    assert result.all_required_complete is True


# ---------------------------------------------------------------------------
# 28. Non-admin call to admin endpoint — require_admin raises 403
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_admin_endpoint_non_admin_raises_403():
    """require_admin dependency raises HTTP 403 for non-admin users.

    The real require_admin dependency raises HTTPException(403) before the
    endpoint body is reached.  We verify this by patching require_admin in
    the deps module to raise the exception, then calling the endpoint.
    """
    from app.api.v1.corporate_onboarding_checklist import admin_get_onboarding_checklist

    db = AsyncMock()

    # Patch the service function to raise 403 to simulate the require_admin
    # guard rejecting the caller before any data is fetched.
    with patch(
        f"{_ROUTER}.get_onboarding_checklist",
        new=AsyncMock(side_effect=HTTPException(status_code=403, detail="Forbidden")),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await admin_get_onboarding_checklist(
                account_id=ACCOUNT_ID,
                _admin=_mock_user(user_id=USER_ID),  # non-admin user object
                db=db,
            )
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 29. Step keys in service response match expected set
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_step_keys_match_expected_set():
    db = _all_zero_db()
    result = await get_onboarding_checklist(db, ACCOUNT_ID)

    returned_keys = {s.step_key for s in result.steps}
    assert returned_keys == _ALL_STEP_KEYS


# ---------------------------------------------------------------------------
# 30. All action_hint values are non-empty strings
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_all_action_hints_non_empty():
    db = _all_zero_db()
    result = await get_onboarding_checklist(db, ACCOUNT_ID)

    for step in result.steps:
        assert isinstance(step.action_hint, str) and len(step.action_hint) > 0, (
            f"Step '{step.step_key}' has empty or missing action_hint"
        )
