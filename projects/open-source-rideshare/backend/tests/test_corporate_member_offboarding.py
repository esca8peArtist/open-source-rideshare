"""Tests for the Corporate Member Offboarding feature.

Service layer (async, mocked DB):
  1.  create_offboarding — happy path
  2.  create_offboarding — 404 when member not in account
  3.  create_offboarding — 409 on duplicate active offboarding
  4.  get_offboarding — found
  5.  get_offboarding — 404 not found
  6.  list_offboardings — all offboardings
  7.  list_offboardings — with status filter
  8.  list_offboardings — empty list
  9.  execute_step — deactivate_membership success
  10. execute_step — close_pending_approvals success
  11. execute_step — cancel_pending_invitations success
  12. execute_step — deactivate_recurring_rides success
  13. execute_step — remove_from_carpool_groups success
  14. execute_step — remove_from_shifts success (no BAM)
  15. execute_step — revoke_delegations success
  16. execute_step — remove_expense_reports success
  17. execute_step — transfer_approval_chain_steps success
  18. execute_step — data_export_generated success
  19. execute_step — 422 on invalid step name
  20. execute_step — 409 if step already completed
  21. execute_step — 409 if offboarding completed (terminal)
  22. execute_step — 409 if offboarding cancelled (terminal)
  23. execute_step — advances status to in_progress from pending
  24. execute_step — 404 offboarding not found
  25. execute_step — member_id is None, step skipped gracefully
  26. complete_offboarding — success
  27. complete_offboarding — 409 if already completed
  28. complete_offboarding — 409 if cancelled
  29. complete_offboarding — 404 not found
  30. cancel_offboarding — success with notes
  31. cancel_offboarding — 409 if already completed
  32. cancel_offboarding — 409 if already cancelled
  33. cancel_offboarding — 404 not found
  34. update_offboarding — partial update
  35. update_offboarding — 404 not found
  36. get_offboarding_summary — correct step counts
  37. get_offboarding_summary — pending steps list correct
  38. get_offboarding_summary — 404 not found
  39. list_pending_steps — returns incomplete steps
  40. list_pending_steps — empty when all complete
  41. list_pending_steps — 404 not found
  42. list_account_offboardings_with_status — returns overview items
  43. list_account_offboardings_with_status — empty list
  44. list_all_platform — returns all
  45. list_all_platform — filtered by account_id
  46. _build_step_details — all steps present
  47. _build_step_details — completed step has timestamp

Schema tests:
  48. OffboardingCreate — valid
  49. OffboardingUpdate — all optional
  50. ExecuteStepRequest — valid
  51. CancelOffboardingRequest — notes optional
  52. OffboardingResponse — fields correct
  53. OffboardingListResponse — items and total
  54. OffboardingStepDetail — fields
  55. OffboardingSummaryResponse — fields
  56. OffboardingOverviewItem — fields

API layer (service functions patched):
  57. POST admin/offboarding — 201 success
  58. POST admin/offboarding — 404 member not in account
  59. POST admin/offboarding — 409 duplicate
  60. GET admin/offboarding — 200 list
  61. GET admin/offboarding?status=pending — 200 filtered
  62. GET admin/offboarding/overview — 200 overview
  63. GET admin/offboarding/{id} — 200 found
  64. GET admin/offboarding/{id} — 404 not found
  65. PUT admin/offboarding/{id} — 200 updated
  66. POST admin/offboarding/{id}/execute-step — 200
  67. POST admin/offboarding/{id}/execute-step — 409 already done
  68. POST admin/offboarding/{id}/complete — 200
  69. POST admin/offboarding/{id}/complete — 409 terminal
  70. POST admin/offboarding/{id}/cancel — 200
  71. GET admin/offboarding/{id}/summary — 200
  72. GET admin/offboarding/{id}/pending-steps — 200 list
  73. GET admin/members/{mid}/offboarding — 200
  74. GET admin/members/{mid}/offboarding — 404 none found
  75. GET platform-admin/offboarding — 200
  76. GET platform-admin/offboarding/{id} — 200
  77. GET platform-admin/offboarding/{id} — 404
  78. GET platform-admin/accounts/{id}/offboarding — 200
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.corporate_member_offboarding import (
    OFFBOARDING_STEPS,
    CorporateMemberOffboarding,
    OffboardingStatus,
    _empty_steps_completed,
)
from app.schemas.corporate_member_offboarding import (
    CancelOffboardingRequest,
    ExecuteStepRequest,
    OffboardingCreate,
    OffboardingListResponse,
    OffboardingOverviewItem,
    OffboardingOverviewResponse,
    OffboardingResponse,
    OffboardingStepDetail,
    OffboardingSummaryResponse,
    OffboardingUpdate,
)
from app.services.corporate_member_offboarding import (
    _build_step_details,
    _empty_steps_completed,
    cancel_offboarding,
    complete_offboarding,
    create_offboarding,
    execute_step,
    get_offboarding,
    get_offboarding_summary,
    list_account_offboardings_with_status,
    list_all_platform,
    list_offboardings,
    list_pending_steps,
    update_offboarding,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NOW = datetime(2026, 4, 16, 10, 0, 0, tzinfo=timezone.utc)
ACCOUNT_ID = 10
OTHER_ACCOUNT_ID = 99
OFFBOARDING_ID = uuid.uuid4()
OFFBOARDING_ID_2 = uuid.uuid4()
MEMBER_USER_ID = 42
INITIATOR_ID = 1
MEMBER_EMAIL = "john.doe@example.com"
MEMBER_NAME = "John Doe"


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_offboarding(
    id: uuid.UUID = OFFBOARDING_ID,
    account_id: int = ACCOUNT_ID,
    member_id: int | None = MEMBER_USER_ID,
    member_email: str = MEMBER_EMAIL,
    member_name: str = MEMBER_NAME,
    initiated_by_id: int | None = INITIATOR_ID,
    status: OffboardingStatus = OffboardingStatus.pending,
    reason: str | None = None,
    last_day=None,
    steps_completed: dict | None = None,
    notes: str | None = None,
    completed_at=None,
    cancelled_at=None,
    cancelled_by_id: int | None = None,
    is_active: bool = True,
) -> CorporateMemberOffboarding:
    ob = CorporateMemberOffboarding()
    ob.id = id
    ob.account_id = account_id
    ob.member_id = member_id
    ob.member_email = member_email
    ob.member_name = member_name
    ob.initiated_by_id = initiated_by_id
    ob.status = status
    ob.reason = reason
    ob.last_day = last_day
    ob.steps_completed = steps_completed if steps_completed is not None else _empty_steps_completed()
    ob.notes = notes
    ob.completed_at = completed_at
    ob.cancelled_at = cancelled_at
    ob.cancelled_by_id = cancelled_by_id
    ob.is_active = is_active
    ob.created_at = NOW
    ob.updated_at = NOW
    return ob


def _async_result(value: Any):
    mock = MagicMock()
    mock.scalar_one_or_none.return_value = value
    mock.scalar.return_value = value
    mock.scalars.return_value.all.return_value = (
        value if isinstance(value, list) else []
    )
    return mock


def _async_list(items: list):
    mock = MagicMock()
    mock.scalars.return_value.all.return_value = items
    mock.scalar_one_or_none.return_value = None
    mock.scalar.return_value = len(items)
    mock.all.return_value = [(item,) for item in items]
    return mock


def _make_db(execute_returns=None, refresh_fn=None):
    db = AsyncMock()
    if execute_returns is not None:
        if isinstance(execute_returns, list):
            db.execute.side_effect = execute_returns
        else:
            db.execute.return_value = execute_returns
    if refresh_fn is not None:
        db.refresh.side_effect = refresh_fn
    db.add = MagicMock()
    return db


# ---------------------------------------------------------------------------
# Response fixtures
# ---------------------------------------------------------------------------

_OFFBOARDING_RESPONSE = OffboardingResponse(
    id=OFFBOARDING_ID,
    account_id=ACCOUNT_ID,
    member_id=MEMBER_USER_ID,
    member_email=MEMBER_EMAIL,
    member_name=MEMBER_NAME,
    initiated_by_id=INITIATOR_ID,
    status=OffboardingStatus.pending,
    reason=None,
    last_day=None,
    steps_completed=_empty_steps_completed(),
    notes=None,
    completed_at=None,
    cancelled_at=None,
    cancelled_by_id=None,
    is_active=True,
    created_at=NOW,
    updated_at=NOW,
)

_OFFBOARDING_LIST_RESPONSE = OffboardingListResponse(
    items=[_OFFBOARDING_RESPONSE], total=1
)

_EMPTY_LIST_RESPONSE = OffboardingListResponse(items=[], total=0)

_SUMMARY_RESPONSE = OffboardingSummaryResponse(
    offboarding=_OFFBOARDING_RESPONSE,
    total_steps=10,
    completed_steps=0,
    pending_steps=list(OFFBOARDING_STEPS),
    step_details=[
        OffboardingStepDetail(
            step_name=s,
            completed=False,
            completed_at=None,
            completed_by_id=None,
            notes=None,
            count=0,
        )
        for s in OFFBOARDING_STEPS
    ],
)

_OVERVIEW_ITEM = OffboardingOverviewItem(
    id=OFFBOARDING_ID,
    account_id=ACCOUNT_ID,
    member_email=MEMBER_EMAIL,
    member_name=MEMBER_NAME,
    status=OffboardingStatus.pending,
    total_steps=10,
    completed_steps=0,
    last_day=None,
    created_at=NOW,
)

_OVERVIEW_RESPONSE = OffboardingOverviewResponse(items=[_OVERVIEW_ITEM], total=1)


# ---------------------------------------------------------------------------
# Helper: make a fake User object
# ---------------------------------------------------------------------------


def _make_user_obj(user_id: int = MEMBER_USER_ID):
    u = MagicMock()
    u.id = user_id
    u.email = MEMBER_EMAIL
    u.name = MEMBER_NAME
    return u


# ---------------------------------------------------------------------------
# Service layer tests: create_offboarding (1-3)
# ---------------------------------------------------------------------------


class TestCreateOffboarding:
    """Tests 1-3: create_offboarding."""

    @pytest.mark.asyncio
    async def test_creates_offboarding_happy_path(self):
        from app.models.corporate import BusinessAccountMember

        bam = MagicMock()
        user_obj = _make_user_obj()
        ob = _make_offboarding()

        bam_result = _async_result(bam)
        no_existing = _async_result(None)
        user_result = _async_result(user_obj)

        db = _make_db(execute_returns=[bam_result, no_existing, user_result])

        async def _refresh(obj):
            obj.id = OFFBOARDING_ID
            obj.account_id = ACCOUNT_ID
            obj.member_id = MEMBER_USER_ID
            obj.member_email = MEMBER_EMAIL
            obj.member_name = MEMBER_NAME
            obj.initiated_by_id = INITIATOR_ID
            obj.status = OffboardingStatus.pending
            obj.steps_completed = _empty_steps_completed()
            obj.is_active = True
            obj.created_at = NOW
            obj.updated_at = NOW

        db.refresh = AsyncMock(side_effect=_refresh)

        result = await create_offboarding(
            db,
            account_id=ACCOUNT_ID,
            member_id=MEMBER_USER_ID,
            initiated_by_id=INITIATOR_ID,
        )
        assert result.account_id == ACCOUNT_ID
        assert result.member_id == MEMBER_USER_ID
        assert result.status == OffboardingStatus.pending
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_404_member_not_in_account(self):
        no_bam = _async_result(None)
        db = _make_db(execute_returns=no_bam)

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await create_offboarding(db, ACCOUNT_ID, MEMBER_USER_ID, INITIATOR_ID)
        assert exc_info.value.status_code == 404
        assert "not found in this corporate account" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_409_on_duplicate_active_offboarding(self):
        bam = MagicMock()
        existing = _make_offboarding()
        bam_result = _async_result(bam)
        existing_result = _async_result(existing)
        db = _make_db(execute_returns=[bam_result, existing_result])

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await create_offboarding(db, ACCOUNT_ID, MEMBER_USER_ID, INITIATOR_ID)
        assert exc_info.value.status_code == 409
        assert "active offboarding already exists" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Service layer tests: get_offboarding (4-5)
# ---------------------------------------------------------------------------


class TestGetOffboarding:
    """Tests 4-5: get_offboarding."""

    @pytest.mark.asyncio
    async def test_returns_offboarding_when_found(self):
        ob = _make_offboarding()
        db = _make_db(execute_returns=_async_result(ob))
        result = await get_offboarding(db, OFFBOARDING_ID, ACCOUNT_ID)
        assert result.id == OFFBOARDING_ID
        assert result.account_id == ACCOUNT_ID

    @pytest.mark.asyncio
    async def test_404_when_not_found(self):
        db = _make_db(execute_returns=_async_result(None))
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await get_offboarding(db, OFFBOARDING_ID, ACCOUNT_ID)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service layer tests: list_offboardings (6-8)
# ---------------------------------------------------------------------------


class TestListOffboardings:
    """Tests 6-8: list_offboardings."""

    @pytest.mark.asyncio
    async def test_returns_all_offboardings(self):
        ob = _make_offboarding()
        db = _make_db(execute_returns=_async_list([ob]))
        result = await list_offboardings(db, ACCOUNT_ID)
        assert result.total == 1
        assert result.items[0].id == OFFBOARDING_ID

    @pytest.mark.asyncio
    async def test_filter_by_status(self):
        ob = _make_offboarding(status=OffboardingStatus.pending)
        db = _make_db(execute_returns=_async_list([ob]))
        result = await list_offboardings(
            db, ACCOUNT_ID, status_filter=OffboardingStatus.pending
        )
        assert result.total == 1
        assert result.items[0].status == OffboardingStatus.pending

    @pytest.mark.asyncio
    async def test_empty_list(self):
        db = _make_db(execute_returns=_async_list([]))
        result = await list_offboardings(db, ACCOUNT_ID)
        assert result.total == 0
        assert result.items == []


# ---------------------------------------------------------------------------
# Service layer tests: execute_step (9-25)
# ---------------------------------------------------------------------------


def _all_steps_completed():
    steps = {}
    for s in OFFBOARDING_STEPS:
        steps[s] = {
            "completed": True,
            "completed_at": NOW.isoformat(),
            "completed_by_id": INITIATOR_ID,
            "notes": None,
            "count": 1,
        }
    return steps


class TestExecuteStep:
    """Tests 9-25: execute_step."""

    def _make_step_db(self, ob, extra_returns=None):
        """Build a mock db where the first execute returns ob, and subsequent calls
        return empty lists (simulating no affected records)."""
        empty = _async_list([])
        ob_result = _async_result(ob)
        returns = [ob_result] + (extra_returns or [empty] * 5)
        db = _make_db(execute_returns=returns)
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_deactivate_membership_success(self):
        ob = _make_offboarding()
        db = self._make_step_db(ob)
        result = await execute_step(
            db, OFFBOARDING_ID, ACCOUNT_ID, "deactivate_membership", INITIATOR_ID
        )
        assert ob.steps_completed["deactivate_membership"]["completed"] is True

    @pytest.mark.asyncio
    async def test_close_pending_approvals_success(self):
        ob = _make_offboarding()
        db = self._make_step_db(ob)
        await execute_step(
            db, OFFBOARDING_ID, ACCOUNT_ID, "close_pending_approvals", INITIATOR_ID
        )
        assert ob.steps_completed["close_pending_approvals"]["completed"] is True

    @pytest.mark.asyncio
    async def test_cancel_pending_invitations_success(self):
        ob = _make_offboarding()
        db = self._make_step_db(ob)
        await execute_step(
            db, OFFBOARDING_ID, ACCOUNT_ID, "cancel_pending_invitations", INITIATOR_ID
        )
        assert ob.steps_completed["cancel_pending_invitations"]["completed"] is True

    @pytest.mark.asyncio
    async def test_deactivate_recurring_rides_success(self):
        ob = _make_offboarding()
        db = self._make_step_db(ob)
        await execute_step(
            db, OFFBOARDING_ID, ACCOUNT_ID, "deactivate_recurring_rides", INITIATOR_ID
        )
        assert ob.steps_completed["deactivate_recurring_rides"]["completed"] is True

    @pytest.mark.asyncio
    async def test_remove_from_carpool_groups_success(self):
        ob = _make_offboarding()
        db = self._make_step_db(ob)
        await execute_step(
            db, OFFBOARDING_ID, ACCOUNT_ID, "remove_from_carpool_groups", INITIATOR_ID
        )
        assert ob.steps_completed["remove_from_carpool_groups"]["completed"] is True

    @pytest.mark.asyncio
    async def test_remove_from_shifts_no_bam(self):
        """When no BusinessAccountMember record exists, step completes with count=0."""
        ob = _make_offboarding()
        ob_result = _async_result(ob)
        no_bam = MagicMock()
        no_bam.all.return_value = []
        db = _make_db(execute_returns=[ob_result, no_bam])
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        await execute_step(
            db, OFFBOARDING_ID, ACCOUNT_ID, "remove_from_shifts", INITIATOR_ID
        )
        assert ob.steps_completed["remove_from_shifts"]["completed"] is True
        assert ob.steps_completed["remove_from_shifts"]["count"] == 0

    @pytest.mark.asyncio
    async def test_revoke_delegations_success(self):
        ob = _make_offboarding()
        db = self._make_step_db(ob)
        await execute_step(
            db, OFFBOARDING_ID, ACCOUNT_ID, "revoke_delegations", INITIATOR_ID
        )
        assert ob.steps_completed["revoke_delegations"]["completed"] is True

    @pytest.mark.asyncio
    async def test_remove_expense_reports_success(self):
        ob = _make_offboarding()
        db = self._make_step_db(ob)
        await execute_step(
            db, OFFBOARDING_ID, ACCOUNT_ID, "remove_expense_reports", INITIATOR_ID
        )
        assert ob.steps_completed["remove_expense_reports"]["completed"] is True

    @pytest.mark.asyncio
    async def test_transfer_approval_chain_steps_success(self):
        ob = _make_offboarding()
        db = self._make_step_db(ob)
        await execute_step(
            db,
            OFFBOARDING_ID,
            ACCOUNT_ID,
            "transfer_approval_chain_steps",
            INITIATOR_ID,
        )
        assert ob.steps_completed["transfer_approval_chain_steps"]["completed"] is True

    @pytest.mark.asyncio
    async def test_data_export_generated_success(self):
        ob = _make_offboarding()
        ob_result = _async_result(ob)
        db = _make_db(execute_returns=ob_result)
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        await execute_step(
            db, OFFBOARDING_ID, ACCOUNT_ID, "data_export_generated", INITIATOR_ID
        )
        assert ob.steps_completed["data_export_generated"]["completed"] is True
        assert ob.steps_completed["data_export_generated"]["count"] == 0

    @pytest.mark.asyncio
    async def test_422_on_invalid_step_name(self):
        ob = _make_offboarding()
        db = _make_db(execute_returns=_async_result(ob))
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await execute_step(
                db, OFFBOARDING_ID, ACCOUNT_ID, "nonexistent_step", INITIATOR_ID
            )
        assert exc_info.value.status_code == 422
        assert "Invalid step name" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_409_step_already_completed(self):
        steps = _empty_steps_completed()
        steps["deactivate_membership"]["completed"] = True
        ob = _make_offboarding(steps_completed=steps)
        db = _make_db(execute_returns=_async_result(ob))
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await execute_step(
                db,
                OFFBOARDING_ID,
                ACCOUNT_ID,
                "deactivate_membership",
                INITIATOR_ID,
            )
        assert exc_info.value.status_code == 409
        assert "already completed" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_409_offboarding_completed_terminal(self):
        ob = _make_offboarding(
            status=OffboardingStatus.completed,
            is_active=False,
            completed_at=NOW,
        )
        db = _make_db(execute_returns=_async_result(ob))
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await execute_step(
                db, OFFBOARDING_ID, ACCOUNT_ID, "deactivate_membership", INITIATOR_ID
            )
        assert exc_info.value.status_code == 409
        assert "completed" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_409_offboarding_cancelled_terminal(self):
        ob = _make_offboarding(
            status=OffboardingStatus.cancelled,
            is_active=False,
            cancelled_at=NOW,
        )
        db = _make_db(execute_returns=_async_result(ob))
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await execute_step(
                db, OFFBOARDING_ID, ACCOUNT_ID, "deactivate_membership", INITIATOR_ID
            )
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_status_advances_to_in_progress(self):
        ob = _make_offboarding(status=OffboardingStatus.pending)
        ob_result = _async_result(ob)
        empty = _async_list([])
        db = _make_db(execute_returns=[ob_result, empty])
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        await execute_step(
            db, OFFBOARDING_ID, ACCOUNT_ID, "deactivate_membership", INITIATOR_ID
        )
        assert ob.status == OffboardingStatus.in_progress

    @pytest.mark.asyncio
    async def test_404_offboarding_not_found(self):
        db = _make_db(execute_returns=_async_result(None))
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await execute_step(
                db, OFFBOARDING_ID, ACCOUNT_ID, "deactivate_membership", INITIATOR_ID
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_step_skipped_gracefully_when_member_id_is_none(self):
        ob = _make_offboarding(member_id=None)
        ob_result = _async_result(ob)
        db = _make_db(execute_returns=ob_result)
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        await execute_step(
            db, OFFBOARDING_ID, ACCOUNT_ID, "data_export_generated", INITIATOR_ID
        )
        assert ob.steps_completed["data_export_generated"]["completed"] is True
        assert ob.steps_completed["data_export_generated"]["count"] == 0


# ---------------------------------------------------------------------------
# Service layer tests: complete_offboarding (26-29)
# ---------------------------------------------------------------------------


class TestCompleteOffboarding:
    """Tests 26-29: complete_offboarding."""

    @pytest.mark.asyncio
    async def test_completes_happy_path(self):
        ob = _make_offboarding(status=OffboardingStatus.in_progress)
        db = _make_db(execute_returns=_async_result(ob))
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        await complete_offboarding(db, OFFBOARDING_ID, ACCOUNT_ID, INITIATOR_ID)
        assert ob.status == OffboardingStatus.completed
        assert ob.is_active is False
        assert ob.completed_at is not None

    @pytest.mark.asyncio
    async def test_409_if_already_completed(self):
        ob = _make_offboarding(
            status=OffboardingStatus.completed, is_active=False, completed_at=NOW
        )
        db = _make_db(execute_returns=_async_result(ob))
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await complete_offboarding(db, OFFBOARDING_ID, ACCOUNT_ID, INITIATOR_ID)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_409_if_cancelled(self):
        ob = _make_offboarding(
            status=OffboardingStatus.cancelled, is_active=False, cancelled_at=NOW
        )
        db = _make_db(execute_returns=_async_result(ob))
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await complete_offboarding(db, OFFBOARDING_ID, ACCOUNT_ID, INITIATOR_ID)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_404_not_found(self):
        db = _make_db(execute_returns=_async_result(None))
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await complete_offboarding(db, OFFBOARDING_ID, ACCOUNT_ID, INITIATOR_ID)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service layer tests: cancel_offboarding (30-33)
# ---------------------------------------------------------------------------


class TestCancelOffboarding:
    """Tests 30-33: cancel_offboarding."""

    @pytest.mark.asyncio
    async def test_cancels_with_notes(self):
        ob = _make_offboarding(status=OffboardingStatus.pending)
        db = _make_db(execute_returns=_async_result(ob))
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        await cancel_offboarding(
            db, OFFBOARDING_ID, ACCOUNT_ID, INITIATOR_ID, notes="Employee rescinded"
        )
        assert ob.status == OffboardingStatus.cancelled
        assert ob.is_active is False
        assert ob.cancelled_at is not None
        assert ob.cancelled_by_id == INITIATOR_ID
        assert ob.notes == "Employee rescinded"

    @pytest.mark.asyncio
    async def test_409_if_already_completed(self):
        ob = _make_offboarding(
            status=OffboardingStatus.completed, is_active=False, completed_at=NOW
        )
        db = _make_db(execute_returns=_async_result(ob))
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await cancel_offboarding(db, OFFBOARDING_ID, ACCOUNT_ID, INITIATOR_ID)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_409_if_already_cancelled(self):
        ob = _make_offboarding(
            status=OffboardingStatus.cancelled, is_active=False, cancelled_at=NOW
        )
        db = _make_db(execute_returns=_async_result(ob))
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await cancel_offboarding(db, OFFBOARDING_ID, ACCOUNT_ID, INITIATOR_ID)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_404_not_found(self):
        db = _make_db(execute_returns=_async_result(None))
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await cancel_offboarding(db, OFFBOARDING_ID, ACCOUNT_ID, INITIATOR_ID)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service layer tests: update_offboarding (34-35)
# ---------------------------------------------------------------------------


class TestUpdateOffboarding:
    """Tests 34-35: update_offboarding."""

    @pytest.mark.asyncio
    async def test_partial_update(self):
        ob = _make_offboarding()
        db = _make_db(execute_returns=_async_result(ob))
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        data = OffboardingUpdate(reason="Resigned for personal reasons")
        await update_offboarding(db, OFFBOARDING_ID, ACCOUNT_ID, data)
        assert ob.reason == "Resigned for personal reasons"

    @pytest.mark.asyncio
    async def test_404_not_found(self):
        db = _make_db(execute_returns=_async_result(None))
        data = OffboardingUpdate(notes="nope")
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await update_offboarding(db, OFFBOARDING_ID, ACCOUNT_ID, data)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service layer tests: get_offboarding_summary (36-38)
# ---------------------------------------------------------------------------


class TestGetOffboardingSummary:
    """Tests 36-38: get_offboarding_summary."""

    @pytest.mark.asyncio
    async def test_correct_step_counts_all_pending(self):
        ob = _make_offboarding()
        db = _make_db(execute_returns=_async_result(ob))
        result = await get_offboarding_summary(db, OFFBOARDING_ID, ACCOUNT_ID)
        assert result.total_steps == 10
        assert result.completed_steps == 0
        assert len(result.pending_steps) == 10

    @pytest.mark.asyncio
    async def test_pending_steps_list_correct(self):
        steps = _empty_steps_completed()
        steps["deactivate_membership"]["completed"] = True
        ob = _make_offboarding(steps_completed=steps)
        db = _make_db(execute_returns=_async_result(ob))
        result = await get_offboarding_summary(db, OFFBOARDING_ID, ACCOUNT_ID)
        assert result.completed_steps == 1
        assert "deactivate_membership" not in result.pending_steps
        assert len(result.pending_steps) == 9

    @pytest.mark.asyncio
    async def test_404_not_found(self):
        db = _make_db(execute_returns=_async_result(None))
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await get_offboarding_summary(db, OFFBOARDING_ID, ACCOUNT_ID)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service layer tests: list_pending_steps (39-41)
# ---------------------------------------------------------------------------


class TestListPendingSteps:
    """Tests 39-41: list_pending_steps."""

    @pytest.mark.asyncio
    async def test_returns_incomplete_steps(self):
        ob = _make_offboarding()
        db = _make_db(execute_returns=_async_result(ob))
        result = await list_pending_steps(db, OFFBOARDING_ID, ACCOUNT_ID)
        assert len(result) == 10
        assert "deactivate_membership" in result

    @pytest.mark.asyncio
    async def test_empty_when_all_complete(self):
        ob = _make_offboarding(steps_completed=_all_steps_completed())
        db = _make_db(execute_returns=_async_result(ob))
        result = await list_pending_steps(db, OFFBOARDING_ID, ACCOUNT_ID)
        assert result == []

    @pytest.mark.asyncio
    async def test_404_not_found(self):
        db = _make_db(execute_returns=_async_result(None))
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await list_pending_steps(db, OFFBOARDING_ID, ACCOUNT_ID)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service layer tests: list_account_offboardings_with_status (42-43)
# ---------------------------------------------------------------------------


class TestListAccountOffboardingsWithStatus:
    """Tests 42-43: list_account_offboardings_with_status."""

    @pytest.mark.asyncio
    async def test_returns_overview_items(self):
        ob = _make_offboarding()
        db = _make_db(execute_returns=_async_list([ob]))
        result = await list_account_offboardings_with_status(db, ACCOUNT_ID)
        assert result.total == 1
        assert result.items[0].member_email == MEMBER_EMAIL
        assert result.items[0].total_steps == 10
        assert result.items[0].completed_steps == 0

    @pytest.mark.asyncio
    async def test_empty_list(self):
        db = _make_db(execute_returns=_async_list([]))
        result = await list_account_offboardings_with_status(db, ACCOUNT_ID)
        assert result.total == 0
        assert result.items == []


# ---------------------------------------------------------------------------
# Service layer tests: list_all_platform (44-45)
# ---------------------------------------------------------------------------


class TestListAllPlatform:
    """Tests 44-45: list_all_platform."""

    @pytest.mark.asyncio
    async def test_returns_all(self):
        ob = _make_offboarding()
        db = _make_db(execute_returns=_async_list([ob]))
        result = await list_all_platform(db)
        assert result.total == 1

    @pytest.mark.asyncio
    async def test_filtered_by_account_id(self):
        ob = _make_offboarding()
        db = _make_db(execute_returns=_async_list([ob]))
        result = await list_all_platform(db, account_id_filter=ACCOUNT_ID)
        assert result.total == 1


# ---------------------------------------------------------------------------
# Unit tests: _build_step_details (46-47)
# ---------------------------------------------------------------------------


class TestBuildStepDetails:
    """Tests 46-47: _build_step_details."""

    def test_all_steps_present(self):
        details = _build_step_details(_empty_steps_completed())
        assert len(details) == 10
        step_names = [d.step_name for d in details]
        for step in OFFBOARDING_STEPS:
            assert step in step_names

    def test_completed_step_has_timestamp(self):
        steps = _empty_steps_completed()
        steps["deactivate_membership"] = {
            "completed": True,
            "completed_at": NOW.isoformat(),
            "completed_by_id": INITIATOR_ID,
            "notes": "done",
            "count": 3,
        }
        details = _build_step_details(steps)
        dm = next(d for d in details if d.step_name == "deactivate_membership")
        assert dm.completed is True
        assert dm.completed_at is not None
        assert dm.count == 3
        assert dm.completed_by_id == INITIATOR_ID


# ---------------------------------------------------------------------------
# Schema validation tests (48-56)
# ---------------------------------------------------------------------------


class TestSchemaValidation:
    """Tests 48-56: schema validation."""

    def test_offboarding_create_valid(self):
        data = OffboardingCreate(member_id=42)
        assert data.member_id == 42
        assert data.reason is None

    def test_offboarding_update_all_optional(self):
        data = OffboardingUpdate()
        assert data.reason is None
        assert data.last_day is None
        assert data.notes is None

    def test_execute_step_request_valid(self):
        data = ExecuteStepRequest(step_name="deactivate_membership")
        assert data.step_name == "deactivate_membership"

    def test_cancel_offboarding_request_notes_optional(self):
        data = CancelOffboardingRequest()
        assert data.notes is None
        data2 = CancelOffboardingRequest(notes="Employee withdrew")
        assert data2.notes == "Employee withdrew"

    def test_offboarding_response_fields(self):
        resp = _OFFBOARDING_RESPONSE
        assert resp.id == OFFBOARDING_ID
        assert resp.account_id == ACCOUNT_ID
        assert resp.member_id == MEMBER_USER_ID
        assert resp.status == OffboardingStatus.pending
        assert isinstance(resp.steps_completed, dict)

    def test_offboarding_list_response(self):
        resp = OffboardingListResponse(items=[_OFFBOARDING_RESPONSE], total=1)
        assert resp.total == 1
        assert resp.items[0].id == OFFBOARDING_ID

    def test_offboarding_step_detail_fields(self):
        detail = OffboardingStepDetail(
            step_name="deactivate_membership",
            completed=True,
            count=2,
        )
        assert detail.step_name == "deactivate_membership"
        assert detail.completed is True
        assert detail.count == 2

    def test_offboarding_summary_response_fields(self):
        assert _SUMMARY_RESPONSE.total_steps == 10
        assert _SUMMARY_RESPONSE.completed_steps == 0
        assert len(_SUMMARY_RESPONSE.pending_steps) == 10
        assert len(_SUMMARY_RESPONSE.step_details) == 10

    def test_offboarding_overview_item_fields(self):
        assert _OVERVIEW_ITEM.account_id == ACCOUNT_ID
        assert _OVERVIEW_ITEM.total_steps == 10
        assert _OVERVIEW_ITEM.completed_steps == 0


# ---------------------------------------------------------------------------
# API layer tests (57-78)
# ---------------------------------------------------------------------------


def _make_api_user(is_admin: bool = False):
    user = MagicMock()
    user.id = 99
    user.is_admin = is_admin
    return user


class TestAPIEndpoints:
    """API layer tests (57-78)."""

    @pytest.fixture
    def client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.api.deps import get_current_user, get_db, require_admin
        from app.api.v1.corporate_member_offboarding import router

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        user = _make_api_user()
        admin_user = _make_api_user(is_admin=True)
        fake_db = AsyncMock()

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: fake_db
        app.dependency_overrides[require_admin] = lambda: admin_user

        return TestClient(app)

    # ---- create ----

    def test_admin_create_201(self, client):
        with (
            patch(
                "app.api.v1.corporate_member_offboarding._resolve_account_id",
                new=AsyncMock(return_value=ACCOUNT_ID),
            ),
            patch(
                "app.api.v1.corporate_member_offboarding._require_account_admin",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.api.v1.corporate_member_offboarding.create_offboarding",
                new=AsyncMock(return_value=_OFFBOARDING_RESPONSE),
            ),
        ):
            resp = client.post(
                "/api/v1/corporate/admin/offboarding",
                json={"member_id": MEMBER_USER_ID},
            )
        assert resp.status_code == 201
        assert resp.json()["member_id"] == MEMBER_USER_ID

    def test_admin_create_404_member_not_in_account(self, client):
        from fastapi import HTTPException

        with (
            patch(
                "app.api.v1.corporate_member_offboarding._resolve_account_id",
                new=AsyncMock(return_value=ACCOUNT_ID),
            ),
            patch(
                "app.api.v1.corporate_member_offboarding._require_account_admin",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.api.v1.corporate_member_offboarding.create_offboarding",
                new=AsyncMock(
                    side_effect=HTTPException(
                        status_code=404, detail="Member not found"
                    )
                ),
            ),
        ):
            resp = client.post(
                "/api/v1/corporate/admin/offboarding",
                json={"member_id": MEMBER_USER_ID},
            )
        assert resp.status_code == 404

    def test_admin_create_409_duplicate(self, client):
        from fastapi import HTTPException

        with (
            patch(
                "app.api.v1.corporate_member_offboarding._resolve_account_id",
                new=AsyncMock(return_value=ACCOUNT_ID),
            ),
            patch(
                "app.api.v1.corporate_member_offboarding._require_account_admin",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.api.v1.corporate_member_offboarding.create_offboarding",
                new=AsyncMock(
                    side_effect=HTTPException(
                        status_code=409, detail="Already exists"
                    )
                ),
            ),
        ):
            resp = client.post(
                "/api/v1/corporate/admin/offboarding",
                json={"member_id": MEMBER_USER_ID},
            )
        assert resp.status_code == 409

    # ---- list ----

    def test_admin_list_200(self, client):
        with (
            patch(
                "app.api.v1.corporate_member_offboarding._resolve_account_id",
                new=AsyncMock(return_value=ACCOUNT_ID),
            ),
            patch(
                "app.api.v1.corporate_member_offboarding._require_account_admin",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.api.v1.corporate_member_offboarding.list_offboardings",
                new=AsyncMock(return_value=_OFFBOARDING_LIST_RESPONSE),
            ),
        ):
            resp = client.get("/api/v1/corporate/admin/offboarding")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_admin_list_with_status_filter(self, client):
        with (
            patch(
                "app.api.v1.corporate_member_offboarding._resolve_account_id",
                new=AsyncMock(return_value=ACCOUNT_ID),
            ),
            patch(
                "app.api.v1.corporate_member_offboarding._require_account_admin",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.api.v1.corporate_member_offboarding.list_offboardings",
                new=AsyncMock(return_value=_OFFBOARDING_LIST_RESPONSE),
            ),
        ):
            resp = client.get("/api/v1/corporate/admin/offboarding?status=pending")
        assert resp.status_code == 200

    # ---- overview ----

    def test_admin_overview_200(self, client):
        with (
            patch(
                "app.api.v1.corporate_member_offboarding._resolve_account_id",
                new=AsyncMock(return_value=ACCOUNT_ID),
            ),
            patch(
                "app.api.v1.corporate_member_offboarding._require_account_admin",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.api.v1.corporate_member_offboarding.list_account_offboardings_with_status",
                new=AsyncMock(return_value=_OVERVIEW_RESPONSE),
            ),
        ):
            resp = client.get("/api/v1/corporate/admin/offboarding/overview")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    # ---- get ----

    def test_admin_get_200(self, client):
        with (
            patch(
                "app.api.v1.corporate_member_offboarding._resolve_account_id",
                new=AsyncMock(return_value=ACCOUNT_ID),
            ),
            patch(
                "app.api.v1.corporate_member_offboarding._require_account_admin",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.api.v1.corporate_member_offboarding.get_offboarding",
                new=AsyncMock(return_value=_OFFBOARDING_RESPONSE),
            ),
        ):
            resp = client.get(f"/api/v1/corporate/admin/offboarding/{OFFBOARDING_ID}")
        assert resp.status_code == 200

    def test_admin_get_404(self, client):
        from fastapi import HTTPException

        with (
            patch(
                "app.api.v1.corporate_member_offboarding._resolve_account_id",
                new=AsyncMock(return_value=ACCOUNT_ID),
            ),
            patch(
                "app.api.v1.corporate_member_offboarding._require_account_admin",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.api.v1.corporate_member_offboarding.get_offboarding",
                new=AsyncMock(
                    side_effect=HTTPException(status_code=404, detail="Not found")
                ),
            ),
        ):
            resp = client.get(f"/api/v1/corporate/admin/offboarding/{OFFBOARDING_ID}")
        assert resp.status_code == 404

    # ---- update ----

    def test_admin_update_200(self, client):
        with (
            patch(
                "app.api.v1.corporate_member_offboarding._resolve_account_id",
                new=AsyncMock(return_value=ACCOUNT_ID),
            ),
            patch(
                "app.api.v1.corporate_member_offboarding._require_account_admin",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.api.v1.corporate_member_offboarding.update_offboarding",
                new=AsyncMock(return_value=_OFFBOARDING_RESPONSE),
            ),
        ):
            resp = client.put(
                f"/api/v1/corporate/admin/offboarding/{OFFBOARDING_ID}",
                json={"reason": "Resigned"},
            )
        assert resp.status_code == 200

    # ---- execute-step ----

    def test_admin_execute_step_200(self, client):
        with (
            patch(
                "app.api.v1.corporate_member_offboarding._resolve_account_id",
                new=AsyncMock(return_value=ACCOUNT_ID),
            ),
            patch(
                "app.api.v1.corporate_member_offboarding._require_account_admin",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.api.v1.corporate_member_offboarding.execute_step",
                new=AsyncMock(return_value=_OFFBOARDING_RESPONSE),
            ),
        ):
            resp = client.post(
                f"/api/v1/corporate/admin/offboarding/{OFFBOARDING_ID}/execute-step",
                json={"step_name": "deactivate_membership"},
            )
        assert resp.status_code == 200

    def test_admin_execute_step_409_already_done(self, client):
        from fastapi import HTTPException

        with (
            patch(
                "app.api.v1.corporate_member_offboarding._resolve_account_id",
                new=AsyncMock(return_value=ACCOUNT_ID),
            ),
            patch(
                "app.api.v1.corporate_member_offboarding._require_account_admin",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.api.v1.corporate_member_offboarding.execute_step",
                new=AsyncMock(
                    side_effect=HTTPException(
                        status_code=409, detail="already completed"
                    )
                ),
            ),
        ):
            resp = client.post(
                f"/api/v1/corporate/admin/offboarding/{OFFBOARDING_ID}/execute-step",
                json={"step_name": "deactivate_membership"},
            )
        assert resp.status_code == 409

    # ---- complete ----

    def test_admin_complete_200(self, client):
        completed_response = OffboardingResponse(
            **{
                **_OFFBOARDING_RESPONSE.model_dump(),
                "status": OffboardingStatus.completed,
                "is_active": False,
                "completed_at": NOW,
            }
        )
        with (
            patch(
                "app.api.v1.corporate_member_offboarding._resolve_account_id",
                new=AsyncMock(return_value=ACCOUNT_ID),
            ),
            patch(
                "app.api.v1.corporate_member_offboarding._require_account_admin",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.api.v1.corporate_member_offboarding.complete_offboarding",
                new=AsyncMock(return_value=completed_response),
            ),
        ):
            resp = client.post(
                f"/api/v1/corporate/admin/offboarding/{OFFBOARDING_ID}/complete"
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    def test_admin_complete_409_terminal(self, client):
        from fastapi import HTTPException

        with (
            patch(
                "app.api.v1.corporate_member_offboarding._resolve_account_id",
                new=AsyncMock(return_value=ACCOUNT_ID),
            ),
            patch(
                "app.api.v1.corporate_member_offboarding._require_account_admin",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.api.v1.corporate_member_offboarding.complete_offboarding",
                new=AsyncMock(
                    side_effect=HTTPException(
                        status_code=409, detail="already completed"
                    )
                ),
            ),
        ):
            resp = client.post(
                f"/api/v1/corporate/admin/offboarding/{OFFBOARDING_ID}/complete"
            )
        assert resp.status_code == 409

    # ---- cancel ----

    def test_admin_cancel_200(self, client):
        cancelled_response = OffboardingResponse(
            **{
                **_OFFBOARDING_RESPONSE.model_dump(),
                "status": OffboardingStatus.cancelled,
                "is_active": False,
                "cancelled_at": NOW,
            }
        )
        with (
            patch(
                "app.api.v1.corporate_member_offboarding._resolve_account_id",
                new=AsyncMock(return_value=ACCOUNT_ID),
            ),
            patch(
                "app.api.v1.corporate_member_offboarding._require_account_admin",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.api.v1.corporate_member_offboarding.cancel_offboarding",
                new=AsyncMock(return_value=cancelled_response),
            ),
        ):
            resp = client.post(
                f"/api/v1/corporate/admin/offboarding/{OFFBOARDING_ID}/cancel",
                json={"notes": "Rescinded"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    # ---- summary ----

    def test_admin_summary_200(self, client):
        with (
            patch(
                "app.api.v1.corporate_member_offboarding._resolve_account_id",
                new=AsyncMock(return_value=ACCOUNT_ID),
            ),
            patch(
                "app.api.v1.corporate_member_offboarding._require_account_admin",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.api.v1.corporate_member_offboarding.get_offboarding_summary",
                new=AsyncMock(return_value=_SUMMARY_RESPONSE),
            ),
        ):
            resp = client.get(
                f"/api/v1/corporate/admin/offboarding/{OFFBOARDING_ID}/summary"
            )
        assert resp.status_code == 200
        assert resp.json()["total_steps"] == 10

    # ---- pending-steps ----

    def test_admin_pending_steps_200(self, client):
        with (
            patch(
                "app.api.v1.corporate_member_offboarding._resolve_account_id",
                new=AsyncMock(return_value=ACCOUNT_ID),
            ),
            patch(
                "app.api.v1.corporate_member_offboarding._require_account_admin",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.api.v1.corporate_member_offboarding.list_pending_steps",
                new=AsyncMock(return_value=list(OFFBOARDING_STEPS)),
            ),
        ):
            resp = client.get(
                f"/api/v1/corporate/admin/offboarding/{OFFBOARDING_ID}/pending-steps"
            )
        assert resp.status_code == 200
        assert len(resp.json()) == 10

    # ---- member offboarding lookup ----

    def test_admin_get_member_offboarding_200(self, client):
        with (
            patch(
                "app.api.v1.corporate_member_offboarding._resolve_account_id",
                new=AsyncMock(return_value=ACCOUNT_ID),
            ),
            patch(
                "app.api.v1.corporate_member_offboarding._require_account_admin",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.api.v1.corporate_member_offboarding.db",
                create=True,
            ),
        ):
            # We need to mock the inline db.execute in the endpoint
            fake_db = AsyncMock()
            ob = _make_offboarding()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = ob
            fake_db.execute = AsyncMock(return_value=mock_result)

            from fastapi import FastAPI
            from fastapi.testclient import TestClient

            from app.api.deps import get_current_user, get_db, require_admin
            from app.api.v1.corporate_member_offboarding import router

            app2 = FastAPI()
            app2.include_router(router, prefix="/api/v1")
            user = _make_api_user()
            app2.dependency_overrides[get_current_user] = lambda: user
            app2.dependency_overrides[get_db] = lambda: fake_db
            app2.dependency_overrides[require_admin] = lambda: _make_api_user(
                is_admin=True
            )

            with (
                patch(
                    "app.api.v1.corporate_member_offboarding._resolve_account_id",
                    new=AsyncMock(return_value=ACCOUNT_ID),
                ),
                patch(
                    "app.api.v1.corporate_member_offboarding._require_account_admin",
                    new=AsyncMock(return_value=None),
                ),
            ):
                c2 = TestClient(app2)
                resp = c2.get(
                    f"/api/v1/corporate/admin/members/{MEMBER_USER_ID}/offboarding"
                )
        assert resp.status_code == 200

    def test_admin_get_member_offboarding_404_none(self, client):
        fake_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        fake_db.execute = AsyncMock(return_value=mock_result)

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.api.deps import get_current_user, get_db, require_admin
        from app.api.v1.corporate_member_offboarding import router

        app2 = FastAPI()
        app2.include_router(router, prefix="/api/v1")
        user = _make_api_user()
        app2.dependency_overrides[get_current_user] = lambda: user
        app2.dependency_overrides[get_db] = lambda: fake_db
        app2.dependency_overrides[require_admin] = lambda: _make_api_user(is_admin=True)

        with (
            patch(
                "app.api.v1.corporate_member_offboarding._resolve_account_id",
                new=AsyncMock(return_value=ACCOUNT_ID),
            ),
            patch(
                "app.api.v1.corporate_member_offboarding._require_account_admin",
                new=AsyncMock(return_value=None),
            ),
        ):
            c2 = TestClient(app2)
            resp = c2.get(
                f"/api/v1/corporate/admin/members/{MEMBER_USER_ID}/offboarding"
            )
        assert resp.status_code == 404

    # ---- platform-admin ----

    def test_platform_list_all_200(self, client):
        with patch(
            "app.api.v1.corporate_member_offboarding.list_all_platform",
            new=AsyncMock(return_value=_OFFBOARDING_LIST_RESPONSE),
        ):
            resp = client.get("/api/v1/corporate/platform-admin/offboarding")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_platform_get_offboarding_200(self, client):
        fake_db = AsyncMock()
        ob = _make_offboarding()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = ob
        fake_db.execute = AsyncMock(return_value=mock_result)

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.api.deps import get_current_user, get_db, require_admin
        from app.api.v1.corporate_member_offboarding import router

        app2 = FastAPI()
        app2.include_router(router, prefix="/api/v1")
        user = _make_api_user()
        app2.dependency_overrides[get_current_user] = lambda: user
        app2.dependency_overrides[get_db] = lambda: fake_db
        app2.dependency_overrides[require_admin] = lambda: _make_api_user(is_admin=True)

        c2 = TestClient(app2)
        resp = c2.get(
            f"/api/v1/corporate/platform-admin/offboarding/{OFFBOARDING_ID}"
        )
        assert resp.status_code == 200

    def test_platform_get_offboarding_404(self, client):
        fake_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        fake_db.execute = AsyncMock(return_value=mock_result)

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.api.deps import get_current_user, get_db, require_admin
        from app.api.v1.corporate_member_offboarding import router

        app2 = FastAPI()
        app2.include_router(router, prefix="/api/v1")
        user = _make_api_user()
        app2.dependency_overrides[get_current_user] = lambda: user
        app2.dependency_overrides[get_db] = lambda: fake_db
        app2.dependency_overrides[require_admin] = lambda: _make_api_user(is_admin=True)

        c2 = TestClient(app2)
        resp = c2.get(
            f"/api/v1/corporate/platform-admin/offboarding/{OFFBOARDING_ID}"
        )
        assert resp.status_code == 404

    def test_platform_list_for_account_200(self, client):
        with patch(
            "app.api.v1.corporate_member_offboarding.list_all_platform",
            new=AsyncMock(return_value=_OFFBOARDING_LIST_RESPONSE),
        ):
            resp = client.get(
                f"/api/v1/corporate/platform-admin/accounts/{ACCOUNT_ID}/offboarding"
            )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
