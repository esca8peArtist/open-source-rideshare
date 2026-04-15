"""Tests for the Corporate Multi-Level Approval Chains feature.

Schema tests (sync):
  1.  ApproverType — both values defined
  2.  EscalationAction — both values defined
  3.  ApprovalChainStepCreate — valid minimal payload
  4.  ApprovalChainStepCreate — step_order must be >= 1
  5.  ApprovalChainCreate — valid payload with one step
  6.  ApprovalChainCreate — steps min_length=1 enforced
  7.  ApprovalChainCreate — steps max_length=5 enforced
  8.  ApprovalChainUpdate — all optional
  9.  ChainRequestCreate — valid payload
  10. StepDecisionRequest — valid approved decision
  11. ApprovalChainResponse — from_attributes
  12. ChainRequestResponse — from_attributes includes total_steps

Service tests (async, mocked DB):
  13. create_chain — success creates chain and steps
  14. create_chain — non-sequential step_order raises 422
  15. get_chain — returns chain with steps
  16. get_chain — not found raises 404
  17. get_chain — wrong account raises 404
  18. list_chains — returns all chains for account
  19. list_chains — filtered by is_active=True
  20. list_chains — filtered by is_active=False
  21. update_chain — partial update succeeds
  22. update_chain — not found raises 404
  23. deactivate_chain — success sets is_active=False
  24. deactivate_chain — already inactive raises 409
  25. deactivate_chain — not found raises 404
  26. delete_chain — success removes chain
  27. delete_chain — pending request raises 409
  28. delete_chain — not found raises 404
  29. find_applicable_chain — matches by min_cost_usd
  30. find_applicable_chain — no match when cost below threshold
  31. find_applicable_chain — matches by cost center
  32. find_applicable_chain — no match when cost center not in list
  33. find_applicable_chain — returns None when no active chains
  34. start_chain_request — success creates pending request
  35. start_chain_request — chain not found raises 404
  36. start_chain_request — inactive chain raises 409
  37. get_chain_request — returns request with decisions
  38. get_chain_request — not found raises 404
  39. list_requests — returns requests for account
  40. cancel_request — success sets status to cancelled
  41. cancel_request — already approved raises 409
  42. decide_step — approved advances to next step
  43. decide_step — approved on last step approves request
  44. decide_step — denied closes request
  45. decide_step — wrong approver for specific_user step raises 403
  46. decide_step — request not pending raises 409
  47. list_pending_for_approver — returns correct requests
  48. list_pending_for_approver — excludes wrong approver for specific_user step

API layer tests:
  49. POST /corporate/accounts/{id}/approval-chains — 201 admin
  50. GET  /corporate/accounts/{id}/approval-chains — 200 admin
  51. GET  /corporate/accounts/{id}/approval-chains/{id} — 200 admin
  52. GET  /corporate/accounts/{id}/approval-chains/{id} — 404 propagated
  53. PUT  /corporate/accounts/{id}/approval-chains/{id} — 200 admin
  54. POST /corporate/accounts/{id}/approval-chains/{id}/deactivate — 200
  55. POST /corporate/accounts/{id}/approval-chains/{id}/deactivate — 409 propagated
  56. DELETE /corporate/accounts/{id}/approval-chains/{id} — 204
  57. GET  /corporate/accounts/{id}/approval-requests/pending-review — 200
  58. POST /corporate/accounts/{id}/approval-requests/{id}/decide — 200
  59. GET  /corporate/accounts/me/approval-chains/applicable — 200 member
  60. GET  /corporate/accounts/me/approval-chains/applicable — 404 not a member
  61. POST /corporate/accounts/me/approval-requests — 201 member
  62. GET  /corporate/accounts/me/approval-requests — 200 member
  63. GET  /corporate/accounts/me/approval-requests/{id} — 200 member
  64. POST /corporate/accounts/me/approval-requests/{id}/cancel — 200 member
  65. GET  /admin/corporate/approval-chains — 200 platform-admin
  66. GET  /admin/corporate/approval-requests — 200 platform-admin
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.corporate_approval_chain import (
    CorporateApprovalChain,
    CorporateApprovalChainRequest,
    CorporateApprovalChainStep,
    CorporateApprovalChainStepDecision,
)
from app.schemas.corporate_approval_chain import (
    ApprovalChainCreate,
    ApprovalChainListResponse,
    ApprovalChainResponse,
    ApprovalChainStepCreate,
    ApprovalChainStepResponse,
    ApprovalChainUpdate,
    ApproverType,
    ChainRequestCreate,
    ChainRequestListResponse,
    ChainRequestResponse,
    EscalationAction,
    StepDecisionRequest,
    StepDecisionResponse,
)
from app.services.corporate_approval_chain import (
    cancel_request,
    create_chain,
    deactivate_chain,
    decide_step,
    delete_chain,
    find_applicable_chain,
    get_chain,
    get_chain_request,
    list_chains,
    list_pending_for_approver,
    list_requests,
    start_chain_request,
    update_chain,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 16, 10, 0, 0, tzinfo=timezone.utc)

ACCOUNT_ID = 10
ADMIN_ID = 99
MEMBER_ID = 20
CHAIN_ID = 1
REQUEST_ID = 100
STEP_ID = 50
DECISION_ID = 200


def _make_step(
    step_id: int = STEP_ID,
    chain_id: int = CHAIN_ID,
    step_order: int = 1,
    approver_type: str = "any_admin",
    approver_user_id: int | None = None,
    timeout_hours: int | None = None,
    escalation_action: str = "deny",
) -> CorporateApprovalChainStep:
    s = CorporateApprovalChainStep()
    s.id = step_id
    s.chain_id = chain_id
    s.step_order = step_order
    s.approver_type = approver_type
    s.approver_user_id = approver_user_id
    s.timeout_hours = timeout_hours
    s.escalation_action = escalation_action
    s.description = None
    return s


def _make_chain(
    chain_id: int = CHAIN_ID,
    account_id: int = ACCOUNT_ID,
    name: str = "Standard Chain",
    is_active: bool = True,
    min_cost_usd: float | None = None,
    applies_to_all: bool = True,
    cost_center_ids: list | None = None,
    created_by_id: int | None = ADMIN_ID,
) -> CorporateApprovalChain:
    c = CorporateApprovalChain()
    c.id = chain_id
    c.account_id = account_id
    c.name = name
    c.description = None
    c.is_active = is_active
    c.min_cost_usd = min_cost_usd
    c.applies_to_all_cost_centers = applies_to_all
    c.cost_center_ids = cost_center_ids
    c.created_by_id = created_by_id
    c.created_at = _NOW
    c.updated_at = _NOW
    return c


def _make_request(
    request_id: int = REQUEST_ID,
    chain_id: int = CHAIN_ID,
    account_id: int = ACCOUNT_ID,
    requester_id: int = MEMBER_ID,
    status: str = "pending",
    current_step_order: int = 1,
    estimated_cost_usd: float | None = None,
) -> CorporateApprovalChainRequest:
    r = CorporateApprovalChainRequest()
    r.id = request_id
    r.chain_id = chain_id
    r.account_id = account_id
    r.requester_id = requester_id
    r.status = status
    r.current_step_order = current_step_order
    r.estimated_cost_usd = estimated_cost_usd
    r.cost_center_id = None
    r.purpose = None
    r.destination_description = None
    r.final_decision_at = None
    r.final_decision_by_id = None
    r.created_at = _NOW
    return r


def _make_decision(
    decision_id: int = DECISION_ID,
    request_id: int = REQUEST_ID,
    step_order: int = 1,
    approver_id: int = ADMIN_ID,
    decision: str = "approved",
) -> CorporateApprovalChainStepDecision:
    d = CorporateApprovalChainStepDecision()
    d.id = decision_id
    d.request_id = request_id
    d.step_order = step_order
    d.approver_id = approver_id
    d.decision = decision
    d.note = None
    d.decided_at = _NOW
    return d


def _make_chain_response(
    chain_id: int = CHAIN_ID,
    account_id: int = ACCOUNT_ID,
    name: str = "Standard Chain",
    is_active: bool = True,
    steps: list | None = None,
) -> ApprovalChainResponse:
    return ApprovalChainResponse(
        id=chain_id,
        account_id=account_id,
        name=name,
        description=None,
        min_cost_usd=None,
        applies_to_all_cost_centers=True,
        cost_center_ids=None,
        is_active=is_active,
        created_by_id=ADMIN_ID,
        created_at=_NOW,
        updated_at=_NOW,
        steps=steps or [],
    )


def _make_request_response(
    request_id: int = REQUEST_ID,
    status: str = "pending",
    current_step_order: int = 1,
    decisions: list | None = None,
    total_steps: int = 2,
) -> ChainRequestResponse:
    return ChainRequestResponse(
        id=request_id,
        chain_id=CHAIN_ID,
        account_id=ACCOUNT_ID,
        requester_id=MEMBER_ID,
        current_step_order=current_step_order,
        status=status,
        estimated_cost_usd=None,
        cost_center_id=None,
        purpose=None,
        destination_description=None,
        final_decision_at=None,
        final_decision_by_id=None,
        created_at=_NOW,
        decisions=decisions or [],
        total_steps=total_steps,
    )


def _make_db(
    scalar_one: object | None = None,
    scalars_all: list | None = None,
) -> AsyncMock:
    """Create a minimal async DB mock."""
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = scalar_one
    mock_result.scalars.return_value.all.return_value = scalars_all or []
    db.execute = AsyncMock(return_value=mock_result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    return db


def _mock_user(user_id: int = ADMIN_ID) -> MagicMock:
    u = MagicMock()
    u.id = user_id
    return u


# ===========================================================================
# 1–12  Schema tests
# ===========================================================================


def test_approver_type_values():
    """ApproverType — both values defined."""
    assert {v.value for v in ApproverType} == {"specific_user", "any_admin"}


def test_escalation_action_values():
    """EscalationAction — both values defined."""
    assert {v.value for v in EscalationAction} == {"skip", "deny"}


def test_approval_chain_step_create_minimal():
    """ApprovalChainStepCreate — valid minimal payload."""
    step = ApprovalChainStepCreate(
        step_order=1,
        approver_type=ApproverType.any_admin,
    )
    assert step.step_order == 1
    assert step.approver_type == ApproverType.any_admin
    assert step.escalation_action == EscalationAction.deny
    assert step.approver_user_id is None


def test_approval_chain_step_create_invalid_order():
    """ApprovalChainStepCreate — step_order must be >= 1."""
    with pytest.raises(ValidationError):
        ApprovalChainStepCreate(step_order=0, approver_type=ApproverType.any_admin)


def test_approval_chain_create_valid():
    """ApprovalChainCreate — valid payload with one step."""
    chain = ApprovalChainCreate(
        name="Manager Approval",
        steps=[
            ApprovalChainStepCreate(
                step_order=1,
                approver_type=ApproverType.specific_user,
                approver_user_id=55,
            )
        ],
    )
    assert chain.name == "Manager Approval"
    assert len(chain.steps) == 1
    assert chain.applies_to_all_cost_centers is True


def test_approval_chain_create_steps_min_length():
    """ApprovalChainCreate — steps min_length=1 enforced."""
    with pytest.raises(ValidationError):
        ApprovalChainCreate(name="Empty", steps=[])


def test_approval_chain_create_steps_max_length():
    """ApprovalChainCreate — steps max_length=5 enforced."""
    steps = [
        ApprovalChainStepCreate(step_order=i, approver_type=ApproverType.any_admin)
        for i in range(1, 7)
    ]
    with pytest.raises(ValidationError):
        ApprovalChainCreate(name="Too many", steps=steps)


def test_approval_chain_update_all_optional():
    """ApprovalChainUpdate — all optional."""
    upd = ApprovalChainUpdate()
    assert upd.name is None
    assert upd.is_active is None
    assert upd.steps is None


def test_chain_request_create_valid():
    """ChainRequestCreate — valid payload."""
    req = ChainRequestCreate(chain_id=CHAIN_ID, estimated_cost_usd=120.50)
    assert req.chain_id == CHAIN_ID
    assert req.estimated_cost_usd == 120.50


def test_step_decision_request_valid():
    """StepDecisionRequest — valid approved decision."""
    from app.schemas.corporate_approval_chain import StepDecision

    req = StepDecisionRequest(decision=StepDecision.approved, note="Looks good.")
    assert req.decision.value == "approved"
    assert req.note == "Looks good."


def test_approval_chain_response_from_attributes():
    """ApprovalChainResponse — from_attributes."""
    chain = _make_chain()
    # Manually set steps (normally loaded separately)
    resp = ApprovalChainResponse(
        id=chain.id,
        account_id=chain.account_id,
        name=chain.name,
        description=chain.description,
        min_cost_usd=chain.min_cost_usd,
        applies_to_all_cost_centers=chain.applies_to_all_cost_centers,
        cost_center_ids=chain.cost_center_ids,
        is_active=chain.is_active,
        created_by_id=chain.created_by_id,
        created_at=chain.created_at,
        updated_at=chain.updated_at,
        steps=[],
    )
    assert resp.id == CHAIN_ID
    assert resp.is_active is True
    assert resp.steps == []


def test_chain_request_response_from_attributes():
    """ChainRequestResponse — from_attributes includes total_steps."""
    resp = _make_request_response(total_steps=3)
    assert resp.total_steps == 3
    assert resp.status == "pending"
    assert resp.decisions == []


# ===========================================================================
# 13–48  Service tests
# ===========================================================================

_SVC = "app.services.corporate_approval_chain"


@pytest.mark.asyncio
async def test_create_chain_success():
    """create_chain — success creates chain and steps."""
    db = _make_db()

    # flush() gives the chain its PK so steps can reference it
    async def _flush_side():
        for call in db.add.call_args_list:
            obj = call[0][0]
            if isinstance(obj, CorporateApprovalChain):
                obj.id = CHAIN_ID

    db.flush.side_effect = _flush_side

    async def _refresh_side(obj):
        if isinstance(obj, CorporateApprovalChain):
            obj.created_at = _NOW
            obj.updated_at = _NOW
        elif isinstance(obj, CorporateApprovalChainStep):
            if obj.id is None:
                obj.id = STEP_ID

    db.refresh.side_effect = _refresh_side

    # _load_chain_steps returns a step with the correct chain_id
    steps_result = MagicMock()
    steps_result.scalars.return_value.all.return_value = [_make_step(chain_id=CHAIN_ID)]
    db.execute.return_value = steps_result

    data = ApprovalChainCreate(
        name="Manager Approval",
        steps=[
            ApprovalChainStepCreate(
                step_order=1,
                approver_type=ApproverType.any_admin,
            )
        ],
    )

    result = await create_chain(db, ACCOUNT_ID, data, created_by_id=ADMIN_ID)

    db.add.assert_called()
    db.commit.assert_called_once()
    assert result.name == "Manager Approval"
    assert result.account_id == ACCOUNT_ID


@pytest.mark.asyncio
async def test_create_chain_non_sequential_steps_raises_422():
    """create_chain — non-sequential step_order raises 422."""
    db = _make_db()
    data = ApprovalChainCreate(
        name="Bad Chain",
        steps=[
            ApprovalChainStepCreate(step_order=1, approver_type=ApproverType.any_admin),
            ApprovalChainStepCreate(step_order=3, approver_type=ApproverType.any_admin),
        ],
    )

    with pytest.raises(HTTPException) as exc_info:
        await create_chain(db, ACCOUNT_ID, data, created_by_id=ADMIN_ID)

    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_get_chain_returns_chain():
    """get_chain — returns chain with steps."""
    chain_row = _make_chain()
    step_row = _make_step()
    db = _make_db(scalar_one=chain_row)

    steps_result = MagicMock()
    steps_result.scalars.return_value.all.return_value = [step_row]

    # First call returns chain, second returns steps
    db.execute.side_effect = [
        MagicMock(**{"scalar_one_or_none.return_value": chain_row}),
        MagicMock(**{"scalars.return_value.all.return_value": [step_row]}),
    ]

    result = await get_chain(db, chain_id=CHAIN_ID, account_id=ACCOUNT_ID)

    assert result.id == CHAIN_ID
    assert result.account_id == ACCOUNT_ID
    assert len(result.steps) == 1


@pytest.mark.asyncio
async def test_get_chain_not_found_raises_404():
    """get_chain — not found raises 404."""
    db = _make_db(scalar_one=None)

    with pytest.raises(HTTPException) as exc_info:
        await get_chain(db, chain_id=999, account_id=ACCOUNT_ID)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_chain_wrong_account_raises_404():
    """get_chain — wrong account raises 404."""
    db = _make_db(scalar_one=None)

    with pytest.raises(HTTPException) as exc_info:
        await get_chain(db, chain_id=CHAIN_ID, account_id=999)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_list_chains_returns_all():
    """list_chains — returns all chains for account."""
    chains = [_make_chain(chain_id=1), _make_chain(chain_id=2)]
    db = _make_db(scalars_all=chains)

    # execute returns chains on first call, empty steps on subsequent calls
    call_results = [
        MagicMock(**{"scalars.return_value.all.return_value": chains}),
        MagicMock(**{"scalars.return_value.all.return_value": []}),
        MagicMock(**{"scalars.return_value.all.return_value": []}),
    ]
    db.execute.side_effect = call_results

    result = await list_chains(db, ACCOUNT_ID)

    assert len(result) == 2


@pytest.mark.asyncio
async def test_list_chains_filtered_active():
    """list_chains — filtered by is_active=True."""
    chains = [_make_chain(is_active=True)]
    call_results = [
        MagicMock(**{"scalars.return_value.all.return_value": chains}),
        MagicMock(**{"scalars.return_value.all.return_value": []}),
    ]
    db = _make_db()
    db.execute.side_effect = call_results

    result = await list_chains(db, ACCOUNT_ID, is_active=True)

    assert len(result) == 1
    assert result[0].is_active is True


@pytest.mark.asyncio
async def test_list_chains_filtered_inactive():
    """list_chains — filtered by is_active=False."""
    chains = [_make_chain(is_active=False)]
    call_results = [
        MagicMock(**{"scalars.return_value.all.return_value": chains}),
        MagicMock(**{"scalars.return_value.all.return_value": []}),
    ]
    db = _make_db()
    db.execute.side_effect = call_results

    result = await list_chains(db, ACCOUNT_ID, is_active=False)

    assert len(result) == 1
    assert result[0].is_active is False


@pytest.mark.asyncio
async def test_update_chain_partial_update():
    """update_chain — partial update succeeds."""
    chain_row = _make_chain()
    db = _make_db()

    call_results = [
        MagicMock(**{"scalar_one_or_none.return_value": chain_row}),  # get chain
        MagicMock(**{"scalars.return_value.all.return_value": []}),   # load steps
    ]
    db.execute.side_effect = call_results

    async def _refresh(obj):
        pass

    db.refresh.side_effect = _refresh

    data = ApprovalChainUpdate(name="Updated Name")
    result = await update_chain(db, CHAIN_ID, ACCOUNT_ID, data)

    assert chain_row.name == "Updated Name"
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_update_chain_not_found_raises_404():
    """update_chain — not found raises 404."""
    db = _make_db(scalar_one=None)

    with pytest.raises(HTTPException) as exc_info:
        await update_chain(db, 999, ACCOUNT_ID, ApprovalChainUpdate(name="X"))

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_deactivate_chain_success():
    """deactivate_chain — success sets is_active=False."""
    chain_row = _make_chain(is_active=True)
    db = _make_db()

    db.execute.side_effect = [
        MagicMock(**{"scalar_one_or_none.return_value": chain_row}),
        MagicMock(**{"scalars.return_value.all.return_value": []}),
    ]

    async def _refresh(obj):
        pass

    db.refresh.side_effect = _refresh

    result = await deactivate_chain(db, CHAIN_ID, ACCOUNT_ID)

    assert chain_row.is_active is False
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_deactivate_chain_already_inactive_raises_409():
    """deactivate_chain — already inactive raises 409."""
    chain_row = _make_chain(is_active=False)
    db = _make_db(scalar_one=chain_row)

    with pytest.raises(HTTPException) as exc_info:
        await deactivate_chain(db, CHAIN_ID, ACCOUNT_ID)

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_deactivate_chain_not_found_raises_404():
    """deactivate_chain — not found raises 404."""
    db = _make_db(scalar_one=None)

    with pytest.raises(HTTPException) as exc_info:
        await deactivate_chain(db, 999, ACCOUNT_ID)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_chain_success():
    """delete_chain — success removes chain."""
    chain_row = _make_chain()
    db = _make_db()

    db.execute.side_effect = [
        MagicMock(**{"scalar_one_or_none.return_value": chain_row}),   # get chain
        MagicMock(**{"scalar_one_or_none.return_value": None}),         # no pending requests
    ]

    await delete_chain(db, CHAIN_ID, ACCOUNT_ID)

    db.delete.assert_called_once_with(chain_row)
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_delete_chain_pending_request_raises_409():
    """delete_chain — pending request raises 409."""
    chain_row = _make_chain()
    pending_request = _make_request()
    db = _make_db()

    db.execute.side_effect = [
        MagicMock(**{"scalar_one_or_none.return_value": chain_row}),
        MagicMock(**{"scalar_one_or_none.return_value": pending_request}),
    ]

    with pytest.raises(HTTPException) as exc_info:
        await delete_chain(db, CHAIN_ID, ACCOUNT_ID)

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_delete_chain_not_found_raises_404():
    """delete_chain — not found raises 404."""
    db = _make_db(scalar_one=None)

    with pytest.raises(HTTPException) as exc_info:
        await delete_chain(db, 999, ACCOUNT_ID)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_find_applicable_chain_matches_by_cost():
    """find_applicable_chain — matches by min_cost_usd."""
    chain_row = _make_chain(min_cost_usd=100.0, applies_to_all=True)
    step_row = _make_step()
    db = _make_db()

    db.execute.side_effect = [
        MagicMock(**{"scalars.return_value.all.return_value": [chain_row]}),
        MagicMock(**{"scalars.return_value.all.return_value": [step_row]}),
    ]

    result = await find_applicable_chain(db, ACCOUNT_ID, estimated_cost_usd=150.0)

    assert result is not None
    assert result.id == CHAIN_ID


@pytest.mark.asyncio
async def test_find_applicable_chain_no_match_below_threshold():
    """find_applicable_chain — no match when cost below threshold."""
    chain_row = _make_chain(min_cost_usd=200.0, applies_to_all=True)
    db = _make_db()

    db.execute.side_effect = [
        MagicMock(**{"scalars.return_value.all.return_value": [chain_row]}),
    ]

    result = await find_applicable_chain(db, ACCOUNT_ID, estimated_cost_usd=50.0)

    assert result is None


@pytest.mark.asyncio
async def test_find_applicable_chain_matches_by_cost_center():
    """find_applicable_chain — matches by cost center."""
    chain_row = _make_chain(applies_to_all=False, cost_center_ids=[5, 10])
    step_row = _make_step()
    db = _make_db()

    db.execute.side_effect = [
        MagicMock(**{"scalars.return_value.all.return_value": [chain_row]}),
        MagicMock(**{"scalars.return_value.all.return_value": [step_row]}),
    ]

    result = await find_applicable_chain(
        db, ACCOUNT_ID, cost_center_id=5
    )

    assert result is not None


@pytest.mark.asyncio
async def test_find_applicable_chain_no_match_wrong_cost_center():
    """find_applicable_chain — no match when cost center not in list."""
    chain_row = _make_chain(applies_to_all=False, cost_center_ids=[5, 10])
    db = _make_db()

    db.execute.side_effect = [
        MagicMock(**{"scalars.return_value.all.return_value": [chain_row]}),
    ]

    result = await find_applicable_chain(db, ACCOUNT_ID, cost_center_id=99)

    assert result is None


@pytest.mark.asyncio
async def test_find_applicable_chain_no_active_chains():
    """find_applicable_chain — returns None when no active chains."""
    db = _make_db()

    db.execute.side_effect = [
        MagicMock(**{"scalars.return_value.all.return_value": []}),
    ]

    result = await find_applicable_chain(db, ACCOUNT_ID)

    assert result is None


@pytest.mark.asyncio
async def test_start_chain_request_success():
    """start_chain_request — success creates pending request."""
    chain_row = _make_chain(is_active=True)
    step_row = _make_step()
    request_row = _make_request()
    db = _make_db()

    db.execute.side_effect = [
        MagicMock(**{"scalar_one_or_none.return_value": chain_row}),   # get chain
        MagicMock(**{"scalars.return_value.all.return_value": [step_row]}),  # load steps
    ]

    async def _refresh(obj):
        obj.id = request_row.id
        obj.chain_id = request_row.chain_id
        obj.account_id = request_row.account_id
        obj.requester_id = request_row.requester_id
        obj.status = request_row.status
        obj.current_step_order = request_row.current_step_order
        obj.estimated_cost_usd = request_row.estimated_cost_usd
        obj.cost_center_id = request_row.cost_center_id
        obj.purpose = request_row.purpose
        obj.destination_description = request_row.destination_description
        obj.final_decision_at = request_row.final_decision_at
        obj.final_decision_by_id = request_row.final_decision_by_id
        obj.created_at = request_row.created_at

    db.refresh.side_effect = _refresh

    data = ChainRequestCreate(chain_id=CHAIN_ID, purpose="Business trip")
    result = await start_chain_request(db, CHAIN_ID, ACCOUNT_ID, MEMBER_ID, data)

    db.add.assert_called_once()
    db.commit.assert_called_once()
    assert result.status == "pending"
    assert result.current_step_order == 1
    assert result.total_steps == 1


@pytest.mark.asyncio
async def test_start_chain_request_chain_not_found_raises_404():
    """start_chain_request — chain not found raises 404."""
    db = _make_db(scalar_one=None)
    data = ChainRequestCreate(chain_id=999)

    with pytest.raises(HTTPException) as exc_info:
        await start_chain_request(db, 999, ACCOUNT_ID, MEMBER_ID, data)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_start_chain_request_inactive_chain_raises_409():
    """start_chain_request — inactive chain raises 409."""
    chain_row = _make_chain(is_active=False)
    db = _make_db(scalar_one=chain_row)
    data = ChainRequestCreate(chain_id=CHAIN_ID)

    with pytest.raises(HTTPException) as exc_info:
        await start_chain_request(db, CHAIN_ID, ACCOUNT_ID, MEMBER_ID, data)

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_get_chain_request_returns_request():
    """get_chain_request — returns request with decisions."""
    request_row = _make_request()
    decision_row = _make_decision()
    step_row = _make_step()
    db = _make_db()

    db.execute.side_effect = [
        MagicMock(**{"scalar_one_or_none.return_value": request_row}),
        MagicMock(**{"scalars.return_value.all.return_value": [decision_row]}),
        MagicMock(**{"scalars.return_value.all.return_value": [step_row]}),
    ]

    result = await get_chain_request(db, REQUEST_ID, ACCOUNT_ID)

    assert result.id == REQUEST_ID
    assert len(result.decisions) == 1
    assert result.total_steps == 1


@pytest.mark.asyncio
async def test_get_chain_request_not_found_raises_404():
    """get_chain_request — not found raises 404."""
    db = _make_db(scalar_one=None)

    with pytest.raises(HTTPException) as exc_info:
        await get_chain_request(db, 999, ACCOUNT_ID)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_list_requests_returns_rows():
    """list_requests — returns requests for account."""
    requests = [_make_request(request_id=1), _make_request(request_id=2)]
    db = _make_db()

    db.execute.side_effect = [
        MagicMock(**{"scalars.return_value.all.return_value": requests}),
        # decisions and steps for request 1
        MagicMock(**{"scalars.return_value.all.return_value": []}),
        MagicMock(**{"scalars.return_value.all.return_value": []}),
        # decisions and steps for request 2
        MagicMock(**{"scalars.return_value.all.return_value": []}),
        MagicMock(**{"scalars.return_value.all.return_value": []}),
    ]

    result = await list_requests(db, ACCOUNT_ID)

    assert len(result) == 2


@pytest.mark.asyncio
async def test_cancel_request_success():
    """cancel_request — success sets status to cancelled."""
    request_row = _make_request(status="pending")
    db = _make_db()

    db.execute.side_effect = [
        MagicMock(**{"scalar_one_or_none.return_value": request_row}),
        MagicMock(**{"scalars.return_value.all.return_value": []}),
        MagicMock(**{"scalars.return_value.all.return_value": []}),
    ]

    async def _refresh(obj):
        pass

    db.refresh.side_effect = _refresh

    result = await cancel_request(db, REQUEST_ID, ACCOUNT_ID, MEMBER_ID)

    assert request_row.status == "cancelled"
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_cancel_request_already_approved_raises_409():
    """cancel_request — already approved raises 409."""
    request_row = _make_request(status="approved")
    db = _make_db(scalar_one=request_row)

    with pytest.raises(HTTPException) as exc_info:
        await cancel_request(db, REQUEST_ID, ACCOUNT_ID, MEMBER_ID)

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_decide_step_approved_advances():
    """decide_step — approved advances to next step."""
    request_row = _make_request(status="pending", current_step_order=1)
    step1 = _make_step(step_order=1, approver_type="any_admin")
    step2 = _make_step(step_id=51, step_order=2, approver_type="any_admin")
    db = _make_db()

    db.execute.side_effect = [
        MagicMock(**{"scalar_one_or_none.return_value": request_row}),   # get request
        MagicMock(**{"scalar_one_or_none.return_value": step1}),          # current step
        MagicMock(**{"scalar_one_or_none.return_value": step2}),          # next step
        MagicMock(**{"scalars.return_value.all.return_value": []}),       # decisions
        MagicMock(**{"scalars.return_value.all.return_value": [step1, step2]}),  # steps
    ]

    async def _refresh(obj):
        pass

    db.refresh.side_effect = _refresh

    result = await decide_step(db, REQUEST_ID, ACCOUNT_ID, ADMIN_ID, "approved")

    assert request_row.current_step_order == 2
    assert request_row.status == "pending"


@pytest.mark.asyncio
async def test_decide_step_approved_last_step_approves_request():
    """decide_step — approved on last step approves request."""
    request_row = _make_request(status="pending", current_step_order=1)
    step1 = _make_step(step_order=1, approver_type="any_admin")
    db = _make_db()

    db.execute.side_effect = [
        MagicMock(**{"scalar_one_or_none.return_value": request_row}),
        MagicMock(**{"scalar_one_or_none.return_value": step1}),
        MagicMock(**{"scalar_one_or_none.return_value": None}),   # no next step
        MagicMock(**{"scalars.return_value.all.return_value": []}),
        MagicMock(**{"scalars.return_value.all.return_value": [step1]}),
    ]

    async def _refresh(obj):
        pass

    db.refresh.side_effect = _refresh

    result = await decide_step(db, REQUEST_ID, ACCOUNT_ID, ADMIN_ID, "approved")

    assert request_row.status == "approved"
    assert request_row.final_decision_by_id == ADMIN_ID
    assert request_row.final_decision_at is not None


@pytest.mark.asyncio
async def test_decide_step_denied_closes_request():
    """decide_step — denied closes request."""
    request_row = _make_request(status="pending", current_step_order=1)
    step1 = _make_step(step_order=1, approver_type="any_admin")
    db = _make_db()

    db.execute.side_effect = [
        MagicMock(**{"scalar_one_or_none.return_value": request_row}),
        MagicMock(**{"scalar_one_or_none.return_value": step1}),
        MagicMock(**{"scalars.return_value.all.return_value": []}),
        MagicMock(**{"scalars.return_value.all.return_value": [step1]}),
    ]

    async def _refresh(obj):
        pass

    db.refresh.side_effect = _refresh

    result = await decide_step(db, REQUEST_ID, ACCOUNT_ID, ADMIN_ID, "denied")

    assert request_row.status == "denied"
    assert request_row.final_decision_by_id == ADMIN_ID


@pytest.mark.asyncio
async def test_decide_step_wrong_specific_user_raises_403():
    """decide_step — wrong approver for specific_user step raises 403."""
    request_row = _make_request(status="pending")
    step = _make_step(
        approver_type="specific_user",
        approver_user_id=55,  # designated approver
    )
    db = _make_db()

    db.execute.side_effect = [
        MagicMock(**{"scalar_one_or_none.return_value": request_row}),
        MagicMock(**{"scalar_one_or_none.return_value": step}),
    ]

    wrong_approver_id = 66
    with pytest.raises(HTTPException) as exc_info:
        await decide_step(
            db, REQUEST_ID, ACCOUNT_ID, wrong_approver_id, "approved"
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_decide_step_not_pending_raises_409():
    """decide_step — request not pending raises 409."""
    request_row = _make_request(status="cancelled")
    db = _make_db(scalar_one=request_row)

    with pytest.raises(HTTPException) as exc_info:
        await decide_step(db, REQUEST_ID, ACCOUNT_ID, ADMIN_ID, "approved")

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_list_pending_for_approver_returns_correct():
    """list_pending_for_approver — returns correct requests."""
    request_row = _make_request(status="pending")
    step = _make_step(approver_type="any_admin")
    db = _make_db()

    db.execute.side_effect = [
        MagicMock(**{"scalars.return_value.all.return_value": [request_row]}),  # pending requests
        MagicMock(**{"scalar_one_or_none.return_value": step}),                  # current step
        MagicMock(**{"scalars.return_value.all.return_value": []}),             # decisions
        MagicMock(**{"scalars.return_value.all.return_value": [step]}),         # steps
    ]

    result = await list_pending_for_approver(db, ACCOUNT_ID, ADMIN_ID)

    assert len(result) == 1
    assert result[0].id == REQUEST_ID


@pytest.mark.asyncio
async def test_list_pending_for_approver_excludes_wrong_approver():
    """list_pending_for_approver — excludes wrong approver for specific_user step."""
    request_row = _make_request(status="pending")
    step = _make_step(approver_type="specific_user", approver_user_id=55)
    db = _make_db()

    db.execute.side_effect = [
        MagicMock(**{"scalars.return_value.all.return_value": [request_row]}),
        MagicMock(**{"scalar_one_or_none.return_value": step}),
    ]

    wrong_approver = 66
    result = await list_pending_for_approver(db, ACCOUNT_ID, wrong_approver)

    assert result == []


# ===========================================================================
# 49–66  API layer tests
# ===========================================================================

_ROUTER = "app.api.v1.corporate_approval_chains"


@pytest.mark.asyncio
async def test_api_admin_create_chain_201():
    """POST /corporate/accounts/{id}/approval-chains — 201 admin."""
    from app.api.v1.corporate_approval_chains import admin_create_chain

    user = _mock_user()
    db = AsyncMock()
    expected = _make_chain_response()

    with patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)), \
         patch(f"{_ROUTER}.create_chain", new=AsyncMock(return_value=expected)):
        payload = ApprovalChainCreate(
            name="Test Chain",
            steps=[ApprovalChainStepCreate(step_order=1, approver_type=ApproverType.any_admin)],
        )
        result = await admin_create_chain(
            account_id=ACCOUNT_ID, payload=payload, user=user, db=db
        )

    assert result.id == CHAIN_ID
    assert result.name == "Standard Chain"


@pytest.mark.asyncio
async def test_api_admin_list_chains_200():
    """GET /corporate/accounts/{id}/approval-chains — 200 admin."""
    from app.api.v1.corporate_approval_chains import admin_list_chains

    user = _mock_user()
    db = AsyncMock()
    chains = [_make_chain_response(), _make_chain_response(chain_id=2)]

    with patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)), \
         patch(f"{_ROUTER}.list_chains", new=AsyncMock(return_value=chains)):
        result = await admin_list_chains(
            account_id=ACCOUNT_ID, is_active=None, user=user, db=db
        )

    assert result.total == 2
    assert len(result.chains) == 2


@pytest.mark.asyncio
async def test_api_admin_get_chain_200():
    """GET /corporate/accounts/{id}/approval-chains/{id} — 200 admin."""
    from app.api.v1.corporate_approval_chains import admin_get_chain

    user = _mock_user()
    db = AsyncMock()
    expected = _make_chain_response()

    with patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)), \
         patch(f"{_ROUTER}.get_chain", new=AsyncMock(return_value=expected)):
        result = await admin_get_chain(
            account_id=ACCOUNT_ID, chain_id=CHAIN_ID, user=user, db=db
        )

    assert result.id == CHAIN_ID


@pytest.mark.asyncio
async def test_api_admin_get_chain_404_propagated():
    """GET /corporate/accounts/{id}/approval-chains/{id} — 404 propagated."""
    from app.api.v1.corporate_approval_chains import admin_get_chain

    user = _mock_user()
    db = AsyncMock()

    with patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)), \
         patch(f"{_ROUTER}.get_chain", new=AsyncMock(
             side_effect=HTTPException(status_code=404, detail="not found")
         )):
        with pytest.raises(HTTPException) as exc_info:
            await admin_get_chain(
                account_id=ACCOUNT_ID, chain_id=999, user=user, db=db
            )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_api_admin_update_chain_200():
    """PUT /corporate/accounts/{id}/approval-chains/{id} — 200 admin."""
    from app.api.v1.corporate_approval_chains import admin_update_chain

    user = _mock_user()
    db = AsyncMock()
    expected = _make_chain_response(name="Updated")

    with patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)), \
         patch(f"{_ROUTER}.update_chain", new=AsyncMock(return_value=expected)):
        result = await admin_update_chain(
            account_id=ACCOUNT_ID,
            chain_id=CHAIN_ID,
            payload=ApprovalChainUpdate(name="Updated"),
            user=user,
            db=db,
        )

    assert result.name == "Updated"


@pytest.mark.asyncio
async def test_api_admin_deactivate_chain_200():
    """POST /corporate/accounts/{id}/approval-chains/{id}/deactivate — 200."""
    from app.api.v1.corporate_approval_chains import admin_deactivate_chain

    user = _mock_user()
    db = AsyncMock()
    expected = _make_chain_response(is_active=False)

    with patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)), \
         patch(f"{_ROUTER}.deactivate_chain", new=AsyncMock(return_value=expected)):
        result = await admin_deactivate_chain(
            account_id=ACCOUNT_ID, chain_id=CHAIN_ID, user=user, db=db
        )

    assert result.is_active is False


@pytest.mark.asyncio
async def test_api_admin_deactivate_chain_409_propagated():
    """POST /corporate/accounts/{id}/approval-chains/{id}/deactivate — 409 propagated."""
    from app.api.v1.corporate_approval_chains import admin_deactivate_chain

    user = _mock_user()
    db = AsyncMock()

    with patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)), \
         patch(f"{_ROUTER}.deactivate_chain", new=AsyncMock(
             side_effect=HTTPException(status_code=409, detail="already inactive")
         )):
        with pytest.raises(HTTPException) as exc_info:
            await admin_deactivate_chain(
                account_id=ACCOUNT_ID, chain_id=CHAIN_ID, user=user, db=db
            )

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_api_admin_delete_chain_204():
    """DELETE /corporate/accounts/{id}/approval-chains/{id} — 204."""
    from app.api.v1.corporate_approval_chains import admin_delete_chain

    user = _mock_user()
    db = AsyncMock()

    with patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)), \
         patch(f"{_ROUTER}.delete_chain", new=AsyncMock(return_value=None)):
        result = await admin_delete_chain(
            account_id=ACCOUNT_ID, chain_id=CHAIN_ID, user=user, db=db
        )

    # Returns None (204 No Content)
    assert result is None


@pytest.mark.asyncio
async def test_api_admin_list_pending_review_200():
    """GET /corporate/accounts/{id}/approval-requests/pending-review — 200."""
    from app.api.v1.corporate_approval_chains import admin_list_pending_review

    user = _mock_user()
    db = AsyncMock()
    requests = [_make_request_response()]

    with patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)), \
         patch(f"{_ROUTER}.list_pending_for_approver", new=AsyncMock(return_value=requests)):
        result = await admin_list_pending_review(
            account_id=ACCOUNT_ID, user=user, db=db
        )

    assert result.total == 1


@pytest.mark.asyncio
async def test_api_admin_decide_step_200():
    """POST /corporate/accounts/{id}/approval-requests/{id}/decide — 200."""
    from app.api.v1.corporate_approval_chains import admin_decide_step
    from app.schemas.corporate_approval_chain import StepDecision

    user = _mock_user()
    db = AsyncMock()
    expected = _make_request_response(status="approved")

    with patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)), \
         patch(f"{_ROUTER}.decide_step", new=AsyncMock(return_value=expected)):
        result = await admin_decide_step(
            account_id=ACCOUNT_ID,
            request_id=REQUEST_ID,
            payload=StepDecisionRequest(decision=StepDecision.approved),
            user=user,
            db=db,
        )

    assert result.status == "approved"


@pytest.mark.asyncio
async def test_api_member_find_applicable_chain_200():
    """GET /corporate/accounts/me/approval-chains/applicable — 200 member."""
    from app.api.v1.corporate_approval_chains import member_find_applicable_chain

    user = _mock_user(user_id=MEMBER_ID)
    db = AsyncMock()
    mock_account = MagicMock()
    mock_account.id = ACCOUNT_ID
    expected = _make_chain_response()

    with patch(f"{_ROUTER}.get_user_account", new=AsyncMock(return_value=mock_account)), \
         patch(f"{_ROUTER}.find_applicable_chain", new=AsyncMock(return_value=expected)):
        result = await member_find_applicable_chain(
            estimated_cost_usd=150.0,
            cost_center_id=None,
            user=user,
            db=db,
        )

    assert result is not None
    assert result.id == CHAIN_ID


@pytest.mark.asyncio
async def test_api_member_find_applicable_chain_404_not_member():
    """GET /corporate/accounts/me/approval-chains/applicable — 404 not a member."""
    from app.api.v1.corporate_approval_chains import member_find_applicable_chain

    user = _mock_user(user_id=MEMBER_ID)
    db = AsyncMock()

    with patch(f"{_ROUTER}.get_user_account", new=AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as exc_info:
            await member_find_applicable_chain(
                estimated_cost_usd=None,
                cost_center_id=None,
                user=user,
                db=db,
            )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_api_member_start_request_201():
    """POST /corporate/accounts/me/approval-requests — 201 member."""
    from app.api.v1.corporate_approval_chains import member_start_request

    user = _mock_user(user_id=MEMBER_ID)
    db = AsyncMock()
    mock_account = MagicMock()
    mock_account.id = ACCOUNT_ID
    expected = _make_request_response()

    with patch(f"{_ROUTER}.get_user_account", new=AsyncMock(return_value=mock_account)), \
         patch(f"{_ROUTER}.start_chain_request", new=AsyncMock(return_value=expected)):
        result = await member_start_request(
            payload=ChainRequestCreate(chain_id=CHAIN_ID),
            user=user,
            db=db,
        )

    assert result.id == REQUEST_ID
    assert result.status == "pending"


@pytest.mark.asyncio
async def test_api_member_list_own_requests_200():
    """GET /corporate/accounts/me/approval-requests — 200 member."""
    from app.api.v1.corporate_approval_chains import member_list_own_requests

    user = _mock_user(user_id=MEMBER_ID)
    db = AsyncMock()
    mock_account = MagicMock()
    mock_account.id = ACCOUNT_ID
    requests = [_make_request_response(), _make_request_response(request_id=101)]

    with patch(f"{_ROUTER}.get_user_account", new=AsyncMock(return_value=mock_account)), \
         patch(f"{_ROUTER}.list_requests", new=AsyncMock(return_value=requests)):
        result = await member_list_own_requests(
            status_filter=None, user=user, db=db
        )

    assert result.total == 2


@pytest.mark.asyncio
async def test_api_member_get_own_request_200():
    """GET /corporate/accounts/me/approval-requests/{id} — 200 member."""
    from app.api.v1.corporate_approval_chains import member_get_own_request

    user = _mock_user(user_id=MEMBER_ID)
    db = AsyncMock()
    mock_account = MagicMock()
    mock_account.id = ACCOUNT_ID
    expected = _make_request_response()

    with patch(f"{_ROUTER}.get_user_account", new=AsyncMock(return_value=mock_account)), \
         patch(f"{_ROUTER}.get_chain_request", new=AsyncMock(return_value=expected)):
        result = await member_get_own_request(
            request_id=REQUEST_ID, user=user, db=db
        )

    assert result.id == REQUEST_ID


@pytest.mark.asyncio
async def test_api_member_cancel_request_200():
    """POST /corporate/accounts/me/approval-requests/{id}/cancel — 200 member."""
    from app.api.v1.corporate_approval_chains import member_cancel_request

    user = _mock_user(user_id=MEMBER_ID)
    db = AsyncMock()
    mock_account = MagicMock()
    mock_account.id = ACCOUNT_ID
    expected = _make_request_response(status="cancelled")

    with patch(f"{_ROUTER}.get_user_account", new=AsyncMock(return_value=mock_account)), \
         patch(f"{_ROUTER}.cancel_request", new=AsyncMock(return_value=expected)):
        result = await member_cancel_request(
            request_id=REQUEST_ID, user=user, db=db
        )

    assert result.status == "cancelled"


@pytest.mark.asyncio
async def test_api_platform_admin_list_chains_200():
    """GET /admin/corporate/approval-chains — 200 platform-admin."""
    from app.api.v1.corporate_approval_chains import platform_admin_list_chains

    admin = _mock_user()
    db = AsyncMock()
    chains = [_make_chain_response(), _make_chain_response(chain_id=2, account_id=50)]

    with patch(f"{_ROUTER}.list_all_chains", new=AsyncMock(return_value=chains)):
        result = await platform_admin_list_chains(
            account_id=None, limit=200, offset=0, _admin=admin, db=db
        )

    assert result.total == 2


@pytest.mark.asyncio
async def test_api_platform_admin_list_requests_200():
    """GET /admin/corporate/approval-requests — 200 platform-admin."""
    from app.api.v1.corporate_approval_chains import platform_admin_list_requests

    admin = _mock_user()
    db = AsyncMock()
    requests = [
        _make_request_response(),
        _make_request_response(request_id=101),
    ]

    with patch(f"{_ROUTER}.list_all_requests", new=AsyncMock(return_value=requests)):
        result = await platform_admin_list_requests(
            account_id=None, limit=200, offset=0, _admin=admin, db=db
        )

    assert result.total == 2
