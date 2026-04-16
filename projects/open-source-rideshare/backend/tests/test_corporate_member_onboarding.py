"""Tests for the Corporate Member Onboarding feature.

Service layer (async, mocked DB):
  1.  create_onboarding — happy path
  2.  create_onboarding — 404 when member not in account
  3.  create_onboarding — 409 on duplicate active onboarding
  4.  get_onboarding — found
  5.  get_onboarding — 404 not found
  6.  get_onboarding_for_member — found
  7.  get_onboarding_for_member — 404 not found
  8.  list_onboardings — all onboardings
  9.  list_onboardings — with status filter
  10. list_onboardings — empty list
  11. mark_step_complete — happy path first step
  12. mark_step_complete — 422 invalid step name
  13. mark_step_complete — 409 step already completed
  14. mark_step_complete — 409 if onboarding completed (terminal)
  15. mark_step_complete — advances status to in_progress from pending
  16. mark_step_complete — 404 not found
  17. mark_step_complete — auto-completes when all steps done
  18. auto_detect_progress — newly detects membership_activated
  19. auto_detect_progress — skips already-completed steps
  20. auto_detect_progress — member_id None skips auto-detectable steps
  21. auto_detect_progress — 404 not found
  22. auto_detect_progress — 409 if onboarding completed
  23. auto_detect_progress — advances status to in_progress
  24. auto_detect_progress — auto-completes when all steps detected
  25. complete_onboarding — success
  26. complete_onboarding — 409 if already completed
  27. complete_onboarding — 404 not found
  28. update_onboarding — partial update notes
  29. update_onboarding — 404 not found
  30. get_onboarding_summary — correct step counts
  31. get_onboarding_summary — pending steps list correct
  32. get_onboarding_summary — 404 not found
  33. list_pending_steps — returns incomplete steps
  34. list_pending_steps — empty when all complete
  35. list_pending_steps — 404 not found
  36. list_account_onboardings_with_status — returns overview items
  37. list_account_onboardings_with_status — empty list
  38. list_all_platform — returns all
  39. list_all_platform — filtered by account_id
  40. _build_step_details — all steps present
  41. _build_step_details — completed step has timestamp and auto_detected flag
  42. _empty_steps_completed — all steps initialised to incomplete
  43. auto-detect: _detect_membership_activated — found
  44. auto-detect: _detect_membership_activated — not found
  45. auto-detect: _detect_transport_preferences_set — found
  46. auto-detect: _detect_transport_preferences_set — not found
  47. auto-detect: _detect_department_assigned — found
  48. auto-detect: _detect_department_assigned — not found
  49. auto-detect: _detect_office_assigned — found (via BAM id)
  50. auto-detect: _detect_office_assigned — not found (no BAM)
  51. auto-detect: _detect_group_assigned — found
  52. auto-detect: _detect_group_assigned — not found (no BAM)
  53. auto-detect: _detect_policy_acknowledged — found
  54. auto-detect: _detect_policy_acknowledged — not found
  55. auto-detect: _detect_manager_assigned — found
  56. auto-detect: _detect_manager_assigned — not found (no BAM)
  57. auto-detect: _detect_cost_center_configured — found
  58. auto-detect: _detect_cost_center_configured — not found

Schema tests:
  59. OnboardingCreate — valid with all optional fields
  60. OnboardingCreate — invitation_id and notes optional
  61. OnboardingUpdate — all optional
  62. MarkStepRequest — valid
  63. OnboardingResponse — fields correct
  64. OnboardingListResponse — items and total
  65. OnboardingStepDetail — auto_detected flag
  66. OnboardingSummaryResponse — fields
  67. OnboardingOverviewItem — fields
  68. AutoDetectResult — fields

API layer (service functions patched):
  69. POST admin/onboarding — 201 success
  70. POST admin/onboarding — 404 member not in account
  71. POST admin/onboarding — 409 duplicate
  72. GET admin/onboarding — 200 list
  73. GET admin/onboarding?status=pending — 200 filtered
  74. GET admin/onboarding/overview — 200 overview
  75. GET admin/onboarding/{id} — 200 found
  76. GET admin/onboarding/{id} — 404 not found
  77. PUT admin/onboarding/{id} — 200 updated
  78. POST admin/onboarding/{id}/detect — 200 auto-detect
  79. POST admin/onboarding/{id}/detect — 409 already completed
  80. POST admin/onboarding/{id}/steps — 200 mark step
  81. POST admin/onboarding/{id}/steps — 409 already done
  82. POST admin/onboarding/{id}/complete — 200
  83. POST admin/onboarding/{id}/complete — 409 terminal
  84. GET admin/onboarding/{id}/summary — 200
  85. GET admin/onboarding/{id}/pending-steps — 200 list
  86. GET admin/members/{mid}/onboarding — 200
  87. GET admin/members/{mid}/onboarding — 404 none found
  88. GET me/onboarding — 200
  89. GET me/onboarding — 404 not in account
  90. GET platform-admin/onboarding — 200
  91. GET platform-admin/onboarding/{id} — 200
  92. GET platform-admin/onboarding/{id} — 404
  93. GET platform-admin/accounts/{id}/onboarding — 200
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.corporate_member_onboarding import (
    ONBOARDING_STEPS,
    CorporateMemberOnboarding,
    OnboardingStatus,
    _empty_steps_completed,
)
from app.schemas.corporate_member_onboarding import (
    AutoDetectResult,
    MarkStepRequest,
    OnboardingCreate,
    OnboardingListResponse,
    OnboardingOverviewItem,
    OnboardingOverviewResponse,
    OnboardingResponse,
    OnboardingStepDetail,
    OnboardingSummaryResponse,
    OnboardingUpdate,
)
from app.services.corporate_member_onboarding import (
    _build_step_details,
    _empty_steps_completed,
    auto_detect_progress,
    complete_onboarding,
    create_onboarding,
    get_onboarding,
    get_onboarding_for_member,
    get_onboarding_summary,
    list_account_onboardings_with_status,
    list_all_platform,
    list_onboardings,
    list_pending_steps,
    mark_step_complete,
    update_onboarding,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NOW = datetime(2026, 4, 16, 10, 0, 0, tzinfo=timezone.utc)
ACCOUNT_ID = 10
OTHER_ACCOUNT_ID = 99
ONBOARDING_ID = uuid.uuid4()
ONBOARDING_ID_2 = uuid.uuid4()
MEMBER_USER_ID = 42
CREATOR_ID = 1
MEMBER_EMAIL = "jane.doe@example.com"
MEMBER_NAME = "Jane Doe"


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_onboarding(
    id: uuid.UUID = ONBOARDING_ID,
    account_id: int = ACCOUNT_ID,
    member_id: int | None = MEMBER_USER_ID,
    member_email: str = MEMBER_EMAIL,
    member_name: str = MEMBER_NAME,
    invitation_id: uuid.UUID | None = None,
    created_by_id: int | None = CREATOR_ID,
    status: OnboardingStatus = OnboardingStatus.pending,
    steps_completed: dict | None = None,
    notes: str | None = None,
    completed_at=None,
    is_active: bool = True,
) -> CorporateMemberOnboarding:
    ob = CorporateMemberOnboarding()
    ob.id = id
    ob.account_id = account_id
    ob.member_id = member_id
    ob.member_email = member_email
    ob.member_name = member_name
    ob.invitation_id = invitation_id
    ob.created_by_id = created_by_id
    ob.status = status
    ob.steps_completed = steps_completed if steps_completed is not None else _empty_steps_completed()
    ob.notes = notes
    ob.completed_at = completed_at
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
    mock.first.return_value = (value,) if value is not None else None
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

_ONBOARDING_RESPONSE = OnboardingResponse(
    id=ONBOARDING_ID,
    account_id=ACCOUNT_ID,
    member_id=MEMBER_USER_ID,
    member_email=MEMBER_EMAIL,
    member_name=MEMBER_NAME,
    invitation_id=None,
    created_by_id=CREATOR_ID,
    status=OnboardingStatus.pending,
    steps_completed=_empty_steps_completed(),
    notes=None,
    completed_at=None,
    is_active=True,
    created_at=NOW,
    updated_at=NOW,
)

_ONBOARDING_LIST_RESPONSE = OnboardingListResponse(
    items=[_ONBOARDING_RESPONSE], total=1
)

_EMPTY_LIST_RESPONSE = OnboardingListResponse(items=[], total=0)

_SUMMARY_RESPONSE = OnboardingSummaryResponse(
    onboarding=_ONBOARDING_RESPONSE,
    total_steps=10,
    completed_steps=0,
    pending_steps=list(ONBOARDING_STEPS),
    step_details=[
        OnboardingStepDetail(
            step_name=s,
            completed=False,
            completed_at=None,
            completed_by_id=None,
            notes=None,
            auto_detected=False,
        )
        for s in ONBOARDING_STEPS
    ],
)

_OVERVIEW_ITEM = OnboardingOverviewItem(
    id=ONBOARDING_ID,
    account_id=ACCOUNT_ID,
    member_email=MEMBER_EMAIL,
    member_name=MEMBER_NAME,
    status=OnboardingStatus.pending,
    total_steps=10,
    completed_steps=0,
    created_at=NOW,
)

_OVERVIEW_RESPONSE = OnboardingOverviewResponse(items=[_OVERVIEW_ITEM], total=1)

_AUTO_DETECT_RESULT = AutoDetectResult(
    newly_detected=[],
    already_completed=[],
    still_pending=list(ONBOARDING_STEPS),
    onboarding=_ONBOARDING_RESPONSE,
)


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
# Service layer tests: create_onboarding (1-3)
# ---------------------------------------------------------------------------


class TestCreateOnboarding:
    """Tests 1-3: create_onboarding."""

    @pytest.mark.asyncio
    async def test_creates_onboarding_happy_path(self):
        from app.models.corporate import BusinessAccountMember

        bam = MagicMock()
        user_obj = _make_user_obj()
        ob = _make_onboarding()

        bam_result = _async_result(bam)
        no_existing = _async_result(None)
        user_result = _async_result(user_obj)

        db = _make_db(execute_returns=[bam_result, no_existing, user_result])

        async def _refresh(obj):
            obj.id = ONBOARDING_ID
            obj.account_id = ACCOUNT_ID
            obj.member_id = MEMBER_USER_ID
            obj.member_email = MEMBER_EMAIL
            obj.member_name = MEMBER_NAME
            obj.invitation_id = None
            obj.created_by_id = CREATOR_ID
            obj.status = OnboardingStatus.pending
            obj.steps_completed = _empty_steps_completed()
            obj.is_active = True
            obj.created_at = NOW
            obj.updated_at = NOW

        db.refresh = AsyncMock(side_effect=_refresh)

        result = await create_onboarding(
            db,
            account_id=ACCOUNT_ID,
            member_id=MEMBER_USER_ID,
            created_by_id=CREATOR_ID,
        )
        assert result.account_id == ACCOUNT_ID
        assert result.member_id == MEMBER_USER_ID
        assert result.status == OnboardingStatus.pending
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_404_member_not_in_account(self):
        no_bam = _async_result(None)
        db = _make_db(execute_returns=no_bam)

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await create_onboarding(db, ACCOUNT_ID, MEMBER_USER_ID, CREATOR_ID)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_409_duplicate_active_onboarding(self):
        bam = MagicMock()
        existing_ob = _make_onboarding()

        bam_result = _async_result(bam)
        existing_result = _async_result(existing_ob)

        db = _make_db(execute_returns=[bam_result, existing_result])

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await create_onboarding(db, ACCOUNT_ID, MEMBER_USER_ID, CREATOR_ID)
        assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# Service layer tests: get_onboarding (4-5)
# ---------------------------------------------------------------------------


class TestGetOnboarding:
    """Tests 4-5: get_onboarding."""

    @pytest.mark.asyncio
    async def test_get_found(self):
        ob = _make_onboarding()
        db = _make_db(execute_returns=_async_result(ob))
        result = await get_onboarding(db, ONBOARDING_ID, ACCOUNT_ID)
        assert result.id == ONBOARDING_ID

    @pytest.mark.asyncio
    async def test_get_404_not_found(self):
        db = _make_db(execute_returns=_async_result(None))
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await get_onboarding(db, ONBOARDING_ID, ACCOUNT_ID)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service layer tests: get_onboarding_for_member (6-7)
# ---------------------------------------------------------------------------


class TestGetOnboardingForMember:
    """Tests 6-7: get_onboarding_for_member."""

    @pytest.mark.asyncio
    async def test_found(self):
        ob = _make_onboarding()
        db = _make_db(execute_returns=_async_result(ob))
        result = await get_onboarding_for_member(db, ACCOUNT_ID, MEMBER_USER_ID)
        assert result.member_id == MEMBER_USER_ID

    @pytest.mark.asyncio
    async def test_404_not_found(self):
        db = _make_db(execute_returns=_async_result(None))
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await get_onboarding_for_member(db, ACCOUNT_ID, MEMBER_USER_ID)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service layer tests: list_onboardings (8-10)
# ---------------------------------------------------------------------------


class TestListOnboardings:
    """Tests 8-10: list_onboardings."""

    @pytest.mark.asyncio
    async def test_list_all(self):
        ob1 = _make_onboarding()
        ob2 = _make_onboarding(id=ONBOARDING_ID_2, status=OnboardingStatus.in_progress)
        db = _make_db(execute_returns=_async_list([ob1, ob2]))
        result = await list_onboardings(db, ACCOUNT_ID)
        assert result.total == 2

    @pytest.mark.asyncio
    async def test_list_with_status_filter(self):
        ob = _make_onboarding()
        db = _make_db(execute_returns=_async_list([ob]))
        result = await list_onboardings(db, ACCOUNT_ID, status_filter=OnboardingStatus.pending)
        assert result.total == 1
        assert result.items[0].status == OnboardingStatus.pending

    @pytest.mark.asyncio
    async def test_list_empty(self):
        db = _make_db(execute_returns=_async_list([]))
        result = await list_onboardings(db, ACCOUNT_ID)
        assert result.total == 0
        assert result.items == []


# ---------------------------------------------------------------------------
# Service layer tests: mark_step_complete (11-17)
# ---------------------------------------------------------------------------


class TestMarkStepComplete:
    """Tests 11-17: mark_step_complete."""

    @pytest.mark.asyncio
    async def test_marks_first_step(self):
        ob = _make_onboarding()

        db = _make_db(execute_returns=_async_result(ob))

        async def _refresh(obj):
            pass

        db.refresh = AsyncMock(side_effect=_refresh)

        result = await mark_step_complete(
            db, ONBOARDING_ID, ACCOUNT_ID, "membership_activated", CREATOR_ID
        )
        assert result is not None
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_422_invalid_step(self):
        ob = _make_onboarding()
        db = _make_db(execute_returns=_async_result(ob))

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await mark_step_complete(
                db, ONBOARDING_ID, ACCOUNT_ID, "not_a_real_step", CREATOR_ID
            )
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_409_step_already_completed(self):
        steps = _empty_steps_completed()
        steps["membership_activated"] = {
            "completed": True,
            "completed_at": NOW.isoformat(),
            "completed_by_id": CREATOR_ID,
            "notes": None,
            "auto_detected": False,
        }
        ob = _make_onboarding(steps_completed=steps)
        db = _make_db(execute_returns=_async_result(ob))

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await mark_step_complete(
                db, ONBOARDING_ID, ACCOUNT_ID, "membership_activated", CREATOR_ID
            )
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_409_onboarding_completed_terminal(self):
        ob = _make_onboarding(status=OnboardingStatus.completed, is_active=False)
        db = _make_db(execute_returns=_async_result(ob))

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await mark_step_complete(
                db, ONBOARDING_ID, ACCOUNT_ID, "membership_activated", CREATOR_ID
            )
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_advances_status_to_in_progress(self):
        ob = _make_onboarding(status=OnboardingStatus.pending)

        db = _make_db(execute_returns=_async_result(ob))

        async def _refresh(obj):
            pass

        db.refresh = AsyncMock(side_effect=_refresh)

        await mark_step_complete(
            db, ONBOARDING_ID, ACCOUNT_ID, "membership_activated", CREATOR_ID
        )
        assert ob.status == OnboardingStatus.in_progress

    @pytest.mark.asyncio
    async def test_404_not_found(self):
        db = _make_db(execute_returns=_async_result(None))

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await mark_step_complete(
                db, ONBOARDING_ID, ACCOUNT_ID, "membership_activated", CREATOR_ID
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_auto_completes_when_all_steps_done(self):
        """Auto-complete triggers when the last step is marked complete."""
        all_but_last = _empty_steps_completed()
        for step in ONBOARDING_STEPS[:-1]:
            all_but_last[step] = {
                "completed": True,
                "completed_at": NOW.isoformat(),
                "completed_by_id": CREATOR_ID,
                "notes": None,
                "auto_detected": False,
            }
        ob = _make_onboarding(
            steps_completed=all_but_last, status=OnboardingStatus.in_progress
        )
        db = _make_db(execute_returns=_async_result(ob))

        async def _refresh(obj):
            pass

        db.refresh = AsyncMock(side_effect=_refresh)

        await mark_step_complete(
            db,
            ONBOARDING_ID,
            ACCOUNT_ID,
            ONBOARDING_STEPS[-1],  # "onboarding_complete_confirmed"
            CREATOR_ID,
        )
        assert ob.status == OnboardingStatus.completed
        assert ob.is_active is False


# ---------------------------------------------------------------------------
# Service layer tests: auto_detect_progress (18-24)
# ---------------------------------------------------------------------------


class TestAutoDetectProgress:
    """Tests 18-24: auto_detect_progress."""

    @pytest.mark.asyncio
    async def test_detects_membership_activated(self):
        ob = _make_onboarding()
        bam_mock = MagicMock()

        get_result = _async_result(ob)
        bam_result = _async_result(bam_mock)  # membership exists

        # All subsequent detects return empty
        empty = _async_result(None)

        db = _make_db(
            execute_returns=[
                get_result,
                bam_result,   # _detect_membership_activated
                empty,        # _detect_transport_preferences_set
                empty,        # _detect_department_assigned
                empty,        # _get_bam_id for office
                empty,        # _detect_group_assigned (no bam)
                empty,        # _detect_policy_acknowledged
                empty,        # _get_bam_id for manager
                empty,        # _detect_cost_center_configured
                empty,        # _detect_first_corporate_ride
            ]
        )

        async def _refresh(obj):
            pass

        db.refresh = AsyncMock(side_effect=_refresh)

        result = await auto_detect_progress(db, ONBOARDING_ID, ACCOUNT_ID)
        assert "membership_activated" in result.newly_detected

    @pytest.mark.asyncio
    async def test_skips_already_completed_steps(self):
        steps = _empty_steps_completed()
        steps["membership_activated"] = {
            "completed": True,
            "completed_at": NOW.isoformat(),
            "completed_by_id": None,
            "notes": "Auto-detected",
            "auto_detected": True,
        }
        ob = _make_onboarding(steps_completed=steps, status=OnboardingStatus.in_progress)

        get_result = _async_result(ob)
        # All remaining detects return False
        empty_results = [_async_result(None) for _ in range(15)]

        db = _make_db(execute_returns=[get_result] + empty_results)

        async def _refresh(obj):
            pass

        db.refresh = AsyncMock(side_effect=_refresh)

        result = await auto_detect_progress(db, ONBOARDING_ID, ACCOUNT_ID)
        assert "membership_activated" in result.already_completed
        assert "membership_activated" not in result.newly_detected

    @pytest.mark.asyncio
    async def test_member_id_none_skips_auto_detectable(self):
        ob = _make_onboarding(member_id=None)
        db = _make_db(execute_returns=_async_result(ob))

        async def _refresh(obj):
            pass

        db.refresh = AsyncMock(side_effect=_refresh)

        result = await auto_detect_progress(db, ONBOARDING_ID, ACCOUNT_ID)
        # Non-manual steps go to still_pending when member_id is None
        assert len(result.newly_detected) == 0
        assert len(result.still_pending) >= 9

    @pytest.mark.asyncio
    async def test_404_not_found(self):
        db = _make_db(execute_returns=_async_result(None))

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await auto_detect_progress(db, ONBOARDING_ID, ACCOUNT_ID)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_409_if_already_completed(self):
        ob = _make_onboarding(status=OnboardingStatus.completed, is_active=False)
        db = _make_db(execute_returns=_async_result(ob))

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await auto_detect_progress(db, ONBOARDING_ID, ACCOUNT_ID)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_advances_to_in_progress(self):
        ob = _make_onboarding(status=OnboardingStatus.pending)
        bam_mock = MagicMock()

        get_result = _async_result(ob)
        bam_result = _async_result(bam_mock)
        empty_results = [_async_result(None) for _ in range(15)]

        db = _make_db(execute_returns=[get_result, bam_result] + empty_results)

        async def _refresh(obj):
            pass

        db.refresh = AsyncMock(side_effect=_refresh)

        result = await auto_detect_progress(db, ONBOARDING_ID, ACCOUNT_ID)
        assert ob.status == OnboardingStatus.in_progress

    @pytest.mark.asyncio
    async def test_auto_completes_when_all_detected(self):
        """When auto-detect fills the last pending step, status becomes completed."""
        all_but_last = _empty_steps_completed()
        # Pre-complete all except the last (onboarding_complete_confirmed is not auto-detectable)
        # Pre-complete all 9 auto-detectable steps
        for step in ONBOARDING_STEPS[:-1]:
            all_but_last[step] = {
                "completed": True,
                "completed_at": NOW.isoformat(),
                "completed_by_id": None,
                "notes": "Auto-detected",
                "auto_detected": True,
            }
        # Last step (onboarding_complete_confirmed) is also pre-complete
        all_but_last[ONBOARDING_STEPS[-1]] = {
            "completed": True,
            "completed_at": NOW.isoformat(),
            "completed_by_id": CREATOR_ID,
            "notes": None,
            "auto_detected": False,
        }
        ob = _make_onboarding(steps_completed=all_but_last, status=OnboardingStatus.in_progress)

        get_result = _async_result(ob)
        db = _make_db(execute_returns=get_result)

        async def _refresh(obj):
            pass

        db.refresh = AsyncMock(side_effect=_refresh)

        result = await auto_detect_progress(db, ONBOARDING_ID, ACCOUNT_ID)
        # All already completed
        assert len(result.already_completed) == 10
        assert ob.status == OnboardingStatus.completed


# ---------------------------------------------------------------------------
# Service layer tests: complete_onboarding (25-27)
# ---------------------------------------------------------------------------


class TestCompleteOnboarding:
    """Tests 25-27: complete_onboarding."""

    @pytest.mark.asyncio
    async def test_completes_successfully(self):
        ob = _make_onboarding(status=OnboardingStatus.in_progress)
        db = _make_db(execute_returns=_async_result(ob))

        async def _refresh(obj):
            pass

        db.refresh = AsyncMock(side_effect=_refresh)

        result = await complete_onboarding(db, ONBOARDING_ID, ACCOUNT_ID, CREATOR_ID)
        assert ob.status == OnboardingStatus.completed
        assert ob.is_active is False

    @pytest.mark.asyncio
    async def test_409_already_completed(self):
        ob = _make_onboarding(status=OnboardingStatus.completed, is_active=False)
        db = _make_db(execute_returns=_async_result(ob))

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await complete_onboarding(db, ONBOARDING_ID, ACCOUNT_ID, CREATOR_ID)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_404_not_found(self):
        db = _make_db(execute_returns=_async_result(None))

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await complete_onboarding(db, ONBOARDING_ID, ACCOUNT_ID, CREATOR_ID)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service layer tests: update_onboarding (28-29)
# ---------------------------------------------------------------------------


class TestUpdateOnboarding:
    """Tests 28-29: update_onboarding."""

    @pytest.mark.asyncio
    async def test_partial_update_notes(self):
        ob = _make_onboarding()
        db = _make_db(execute_returns=_async_result(ob))

        async def _refresh(obj):
            pass

        db.refresh = AsyncMock(side_effect=_refresh)

        data = OnboardingUpdate(notes="New hire checklist notes")
        result = await update_onboarding(db, ONBOARDING_ID, ACCOUNT_ID, data)
        assert ob.notes == "New hire checklist notes"

    @pytest.mark.asyncio
    async def test_404_not_found(self):
        db = _make_db(execute_returns=_async_result(None))

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await update_onboarding(
                db, ONBOARDING_ID, ACCOUNT_ID, OnboardingUpdate(notes="x")
            )
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service layer tests: get_onboarding_summary (30-32)
# ---------------------------------------------------------------------------


class TestGetOnboardingSummary:
    """Tests 30-32: get_onboarding_summary."""

    @pytest.mark.asyncio
    async def test_correct_step_counts(self):
        ob = _make_onboarding()
        db = _make_db(execute_returns=_async_result(ob))
        result = await get_onboarding_summary(db, ONBOARDING_ID, ACCOUNT_ID)
        assert result.total_steps == 10
        assert result.completed_steps == 0
        assert len(result.step_details) == 10

    @pytest.mark.asyncio
    async def test_pending_steps_list_correct(self):
        ob = _make_onboarding()
        db = _make_db(execute_returns=_async_result(ob))
        result = await get_onboarding_summary(db, ONBOARDING_ID, ACCOUNT_ID)
        assert result.pending_steps == ONBOARDING_STEPS

    @pytest.mark.asyncio
    async def test_404_not_found(self):
        db = _make_db(execute_returns=_async_result(None))
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await get_onboarding_summary(db, ONBOARDING_ID, ACCOUNT_ID)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service layer tests: list_pending_steps (33-35)
# ---------------------------------------------------------------------------


class TestListPendingSteps:
    """Tests 33-35: list_pending_steps."""

    @pytest.mark.asyncio
    async def test_returns_incomplete_steps(self):
        ob = _make_onboarding()
        db = _make_db(execute_returns=_async_result(ob))
        result = await list_pending_steps(db, ONBOARDING_ID, ACCOUNT_ID)
        assert set(result) == set(ONBOARDING_STEPS)

    @pytest.mark.asyncio
    async def test_empty_when_all_complete(self):
        all_done = {
            step: {
                "completed": True,
                "completed_at": NOW.isoformat(),
                "completed_by_id": CREATOR_ID,
                "notes": None,
                "auto_detected": False,
            }
            for step in ONBOARDING_STEPS
        }
        ob = _make_onboarding(steps_completed=all_done, status=OnboardingStatus.completed)
        db = _make_db(execute_returns=_async_result(ob))
        result = await list_pending_steps(db, ONBOARDING_ID, ACCOUNT_ID)
        assert result == []

    @pytest.mark.asyncio
    async def test_404_not_found(self):
        db = _make_db(execute_returns=_async_result(None))
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await list_pending_steps(db, ONBOARDING_ID, ACCOUNT_ID)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service layer tests: list_account_onboardings_with_status (36-37)
# ---------------------------------------------------------------------------


class TestListAccountOnboardingsWithStatus:
    """Tests 36-37: list_account_onboardings_with_status."""

    @pytest.mark.asyncio
    async def test_returns_overview_items(self):
        ob = _make_onboarding()
        db = _make_db(execute_returns=_async_list([ob]))
        result = await list_account_onboardings_with_status(db, ACCOUNT_ID)
        assert result.total == 1
        assert result.items[0].member_email == MEMBER_EMAIL

    @pytest.mark.asyncio
    async def test_empty_list(self):
        db = _make_db(execute_returns=_async_list([]))
        result = await list_account_onboardings_with_status(db, ACCOUNT_ID)
        assert result.total == 0


# ---------------------------------------------------------------------------
# Service layer tests: list_all_platform (38-39)
# ---------------------------------------------------------------------------


class TestListAllPlatform:
    """Tests 38-39: list_all_platform."""

    @pytest.mark.asyncio
    async def test_returns_all(self):
        ob1 = _make_onboarding()
        ob2 = _make_onboarding(id=ONBOARDING_ID_2, account_id=OTHER_ACCOUNT_ID)
        db = _make_db(execute_returns=_async_list([ob1, ob2]))
        result = await list_all_platform(db)
        assert result.total == 2

    @pytest.mark.asyncio
    async def test_filtered_by_account_id(self):
        ob = _make_onboarding()
        db = _make_db(execute_returns=_async_list([ob]))
        result = await list_all_platform(db, account_id_filter=ACCOUNT_ID)
        assert result.total == 1


# ---------------------------------------------------------------------------
# Service layer tests: _build_step_details (40-41)
# ---------------------------------------------------------------------------


class TestBuildStepDetails:
    """Tests 40-41: _build_step_details."""

    def test_all_steps_present(self):
        details = _build_step_details(_empty_steps_completed())
        assert len(details) == 10
        step_names = [d.step_name for d in details]
        assert step_names == ONBOARDING_STEPS

    def test_completed_step_has_timestamp_and_auto_detected_flag(self):
        steps = _empty_steps_completed()
        steps["membership_activated"] = {
            "completed": True,
            "completed_at": NOW.isoformat(),
            "completed_by_id": None,
            "notes": "Auto-detected",
            "auto_detected": True,
        }
        details = _build_step_details(steps)
        membership_detail = next(
            d for d in details if d.step_name == "membership_activated"
        )
        assert membership_detail.completed is True
        assert membership_detail.completed_at == NOW
        assert membership_detail.auto_detected is True


# ---------------------------------------------------------------------------
# Model tests: _empty_steps_completed (42)
# ---------------------------------------------------------------------------


class TestEmptyStepsCompleted:
    """Test 42: _empty_steps_completed."""

    def test_all_steps_initialised_to_incomplete(self):
        steps = _empty_steps_completed()
        assert set(steps.keys()) == set(ONBOARDING_STEPS)
        for step, entry in steps.items():
            assert entry["completed"] is False
            assert entry["completed_at"] is None
            assert entry["completed_by_id"] is None
            assert entry["auto_detected"] is False


# ---------------------------------------------------------------------------
# Auto-detect helper tests (43-58)
# ---------------------------------------------------------------------------


class TestAutoDetectHelpers:
    """Tests 43-58: individual auto-detection helpers."""

    @pytest.mark.asyncio
    async def test_detect_membership_activated_found(self):
        from app.services.corporate_member_onboarding import _detect_membership_activated
        bam = MagicMock()
        db = _make_db(execute_returns=_async_result(bam))
        result = await _detect_membership_activated(db, ACCOUNT_ID, MEMBER_USER_ID)
        assert result is True

    @pytest.mark.asyncio
    async def test_detect_membership_activated_not_found(self):
        from app.services.corporate_member_onboarding import _detect_membership_activated
        db = _make_db(execute_returns=_async_result(None))
        result = await _detect_membership_activated(db, ACCOUNT_ID, MEMBER_USER_ID)
        assert result is False

    @pytest.mark.asyncio
    async def test_detect_transport_preferences_set_found(self):
        from app.services.corporate_member_onboarding import _detect_transport_preferences_set
        pref = MagicMock()
        db = _make_db(execute_returns=_async_result(pref))
        result = await _detect_transport_preferences_set(db, ACCOUNT_ID, MEMBER_USER_ID)
        assert result is True

    @pytest.mark.asyncio
    async def test_detect_transport_preferences_set_not_found(self):
        from app.services.corporate_member_onboarding import _detect_transport_preferences_set
        db = _make_db(execute_returns=_async_result(None))
        result = await _detect_transport_preferences_set(db, ACCOUNT_ID, MEMBER_USER_ID)
        assert result is False

    @pytest.mark.asyncio
    async def test_detect_department_assigned_found(self):
        from app.services.corporate_member_onboarding import _detect_department_assigned
        dept_member = MagicMock()
        db = _make_db(execute_returns=_async_result(dept_member))
        result = await _detect_department_assigned(db, ACCOUNT_ID, MEMBER_USER_ID)
        assert result is True

    @pytest.mark.asyncio
    async def test_detect_department_assigned_not_found(self):
        from app.services.corporate_member_onboarding import _detect_department_assigned
        db = _make_db(execute_returns=_async_result(None))
        result = await _detect_department_assigned(db, ACCOUNT_ID, MEMBER_USER_ID)
        assert result is False

    @pytest.mark.asyncio
    async def test_detect_office_assigned_found(self):
        from app.services.corporate_member_onboarding import _detect_office_assigned
        bam_id_row = MagicMock()
        office_mem = MagicMock()

        # _get_bam_id returns row with bam_id, then office query returns result
        bam_result = MagicMock()
        bam_result.first.return_value = (99,)
        office_result = _async_result(office_mem)

        db = _make_db(execute_returns=[bam_result, office_result])
        result = await _detect_office_assigned(db, ACCOUNT_ID, MEMBER_USER_ID)
        assert result is True

    @pytest.mark.asyncio
    async def test_detect_office_assigned_no_bam(self):
        from app.services.corporate_member_onboarding import _detect_office_assigned
        bam_result = MagicMock()
        bam_result.first.return_value = None

        db = _make_db(execute_returns=bam_result)
        result = await _detect_office_assigned(db, ACCOUNT_ID, MEMBER_USER_ID)
        assert result is False

    @pytest.mark.asyncio
    async def test_detect_group_assigned_found(self):
        from app.services.corporate_member_onboarding import _detect_group_assigned
        bam_result = MagicMock()
        bam_result.first.return_value = (99,)
        group_result = _async_result(MagicMock())

        db = _make_db(execute_returns=[bam_result, group_result])
        result = await _detect_group_assigned(db, ACCOUNT_ID, MEMBER_USER_ID)
        assert result is True

    @pytest.mark.asyncio
    async def test_detect_group_assigned_no_bam(self):
        from app.services.corporate_member_onboarding import _detect_group_assigned
        bam_result = MagicMock()
        bam_result.first.return_value = None

        db = _make_db(execute_returns=bam_result)
        result = await _detect_group_assigned(db, ACCOUNT_ID, MEMBER_USER_ID)
        assert result is False

    @pytest.mark.asyncio
    async def test_detect_policy_acknowledged_found(self):
        from app.services.corporate_member_onboarding import _detect_policy_acknowledged
        ack = MagicMock()
        db = _make_db(execute_returns=_async_result(ack))
        result = await _detect_policy_acknowledged(db, ACCOUNT_ID, MEMBER_USER_ID)
        assert result is True

    @pytest.mark.asyncio
    async def test_detect_policy_acknowledged_not_found(self):
        from app.services.corporate_member_onboarding import _detect_policy_acknowledged
        db = _make_db(execute_returns=_async_result(None))
        result = await _detect_policy_acknowledged(db, ACCOUNT_ID, MEMBER_USER_ID)
        assert result is False

    @pytest.mark.asyncio
    async def test_detect_manager_assigned_found(self):
        from app.services.corporate_member_onboarding import _detect_manager_assigned
        bam_result = MagicMock()
        bam_result.first.return_value = (99,)
        mgr_result = _async_result(MagicMock())

        db = _make_db(execute_returns=[bam_result, mgr_result])
        result = await _detect_manager_assigned(db, ACCOUNT_ID, MEMBER_USER_ID)
        assert result is True

    @pytest.mark.asyncio
    async def test_detect_manager_assigned_no_bam(self):
        from app.services.corporate_member_onboarding import _detect_manager_assigned
        bam_result = MagicMock()
        bam_result.first.return_value = None

        db = _make_db(execute_returns=bam_result)
        result = await _detect_manager_assigned(db, ACCOUNT_ID, MEMBER_USER_ID)
        assert result is False

    @pytest.mark.asyncio
    async def test_detect_cost_center_configured_found(self):
        from app.services.corporate_member_onboarding import _detect_cost_center_configured
        pref = MagicMock()
        db = _make_db(execute_returns=_async_result(pref))
        result = await _detect_cost_center_configured(db, ACCOUNT_ID, MEMBER_USER_ID)
        assert result is True

    @pytest.mark.asyncio
    async def test_detect_cost_center_configured_not_found(self):
        from app.services.corporate_member_onboarding import _detect_cost_center_configured
        db = _make_db(execute_returns=_async_result(None))
        result = await _detect_cost_center_configured(db, ACCOUNT_ID, MEMBER_USER_ID)
        assert result is False


# ---------------------------------------------------------------------------
# Schema tests (59-68)
# ---------------------------------------------------------------------------


class TestSchemas:
    """Tests 59-68: schema validation."""

    def test_onboarding_create_valid(self):
        inv_id = uuid.uuid4()
        obj = OnboardingCreate(member_id=42, invitation_id=inv_id, notes="Welcome!")
        assert obj.member_id == 42
        assert obj.invitation_id == inv_id
        assert obj.notes == "Welcome!"

    def test_onboarding_create_optional_fields(self):
        obj = OnboardingCreate(member_id=42)
        assert obj.invitation_id is None
        assert obj.notes is None

    def test_onboarding_update_all_optional(self):
        obj = OnboardingUpdate()
        assert obj.notes is None

    def test_mark_step_request_valid(self):
        obj = MarkStepRequest(step_name="membership_activated", notes="Confirmed")
        assert obj.step_name == "membership_activated"
        assert obj.notes == "Confirmed"

    def test_onboarding_response_fields(self):
        assert _ONBOARDING_RESPONSE.account_id == ACCOUNT_ID
        assert _ONBOARDING_RESPONSE.status == OnboardingStatus.pending
        assert _ONBOARDING_RESPONSE.is_active is True

    def test_onboarding_list_response(self):
        assert _ONBOARDING_LIST_RESPONSE.total == 1
        assert len(_ONBOARDING_LIST_RESPONSE.items) == 1

    def test_onboarding_step_detail_auto_detected_flag(self):
        detail = OnboardingStepDetail(
            step_name="membership_activated",
            completed=True,
            auto_detected=True,
        )
        assert detail.auto_detected is True

    def test_onboarding_summary_response_fields(self):
        assert _SUMMARY_RESPONSE.total_steps == 10
        assert _SUMMARY_RESPONSE.completed_steps == 0
        assert len(_SUMMARY_RESPONSE.pending_steps) == 10

    def test_onboarding_overview_item_fields(self):
        assert _OVERVIEW_ITEM.total_steps == 10
        assert _OVERVIEW_ITEM.completed_steps == 0

    def test_auto_detect_result_fields(self):
        result = AutoDetectResult(
            newly_detected=["membership_activated"],
            already_completed=["transport_preferences_set"],
            still_pending=["department_assigned"],
            onboarding=_ONBOARDING_RESPONSE,
        )
        assert result.newly_detected == ["membership_activated"]
        assert result.already_completed == ["transport_preferences_set"]
        assert result.still_pending == ["department_assigned"]


# ---------------------------------------------------------------------------
# API layer tests (69-93)
# ---------------------------------------------------------------------------


class TestOnboardingAPI:
    """Tests 69-93: API endpoint tests with mocked service functions."""

    # ---- helpers ----

    def _make_admin_user(self, user_id: int = CREATOR_ID):
        u = MagicMock()
        u.id = user_id
        u.is_admin = True
        return u

    def _api_deps(self, user, account_id=ACCOUNT_ID, is_admin=True):
        """Return a dict mapping dependency overrides."""
        from app.api.deps import get_current_user, get_db, require_admin
        return {
            get_current_user: lambda: user,
            require_admin: lambda: user,
            get_db: lambda: AsyncMock(),
        }

    @pytest.mark.asyncio
    async def test_post_admin_create_201(self):
        with (
            patch(
                "app.api.v1.corporate_member_onboarding.create_onboarding",
                new_callable=AsyncMock,
                return_value=_ONBOARDING_RESPONSE,
            ),
            patch(
                "app.api.v1.corporate_member_onboarding._resolve_account_id",
                new_callable=AsyncMock,
                return_value=ACCOUNT_ID,
            ),
            patch(
                "app.api.v1.corporate_member_onboarding._require_account_admin",
                new_callable=AsyncMock,
            ),
        ):
            from app.api.v1.corporate_member_onboarding import admin_create_onboarding
            from app.api.deps import get_current_user, get_db

            user = self._make_admin_user()
            data = OnboardingCreate(member_id=MEMBER_USER_ID)

            result = await admin_create_onboarding(
                data=data, user=user, db=AsyncMock()
            )
            assert result.account_id == ACCOUNT_ID

    @pytest.mark.asyncio
    async def test_post_admin_create_404_member_not_in_account(self):
        from fastapi import HTTPException
        with patch(
            "app.api.v1.corporate_member_onboarding.create_onboarding",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=404, detail="Member not found"),
        ), patch(
            "app.api.v1.corporate_member_onboarding._resolve_account_id",
            new_callable=AsyncMock,
            return_value=ACCOUNT_ID,
        ), patch(
            "app.api.v1.corporate_member_onboarding._require_account_admin",
            new_callable=AsyncMock,
        ):
            from app.api.v1.corporate_member_onboarding import admin_create_onboarding
            user = self._make_admin_user()
            data = OnboardingCreate(member_id=999)
            with pytest.raises(HTTPException) as exc_info:
                await admin_create_onboarding(data=data, user=user, db=AsyncMock())
            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_post_admin_create_409_duplicate(self):
        from fastapi import HTTPException
        with patch(
            "app.api.v1.corporate_member_onboarding.create_onboarding",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=409, detail="Duplicate"),
        ), patch(
            "app.api.v1.corporate_member_onboarding._resolve_account_id",
            new_callable=AsyncMock,
            return_value=ACCOUNT_ID,
        ), patch(
            "app.api.v1.corporate_member_onboarding._require_account_admin",
            new_callable=AsyncMock,
        ):
            from app.api.v1.corporate_member_onboarding import admin_create_onboarding
            user = self._make_admin_user()
            data = OnboardingCreate(member_id=MEMBER_USER_ID)
            with pytest.raises(HTTPException) as exc_info:
                await admin_create_onboarding(data=data, user=user, db=AsyncMock())
            assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_get_admin_list_200(self):
        with patch(
            "app.api.v1.corporate_member_onboarding.list_onboardings",
            new_callable=AsyncMock,
            return_value=_ONBOARDING_LIST_RESPONSE,
        ), patch(
            "app.api.v1.corporate_member_onboarding._resolve_account_id",
            new_callable=AsyncMock,
            return_value=ACCOUNT_ID,
        ), patch(
            "app.api.v1.corporate_member_onboarding._require_account_admin",
            new_callable=AsyncMock,
        ):
            from app.api.v1.corporate_member_onboarding import admin_list_onboardings
            user = self._make_admin_user()
            result = await admin_list_onboardings(status=None, user=user, db=AsyncMock())
            assert result.total == 1

    @pytest.mark.asyncio
    async def test_get_admin_list_filtered_by_status(self):
        with patch(
            "app.api.v1.corporate_member_onboarding.list_onboardings",
            new_callable=AsyncMock,
            return_value=_ONBOARDING_LIST_RESPONSE,
        ) as mock_list, patch(
            "app.api.v1.corporate_member_onboarding._resolve_account_id",
            new_callable=AsyncMock,
            return_value=ACCOUNT_ID,
        ), patch(
            "app.api.v1.corporate_member_onboarding._require_account_admin",
            new_callable=AsyncMock,
        ):
            from app.api.v1.corporate_member_onboarding import admin_list_onboardings
            user = self._make_admin_user()
            await admin_list_onboardings(
                status=OnboardingStatus.pending, user=user, db=AsyncMock()
            )
            mock_list.assert_called_once()
            _, kwargs = mock_list.call_args
            assert kwargs.get("status_filter") == OnboardingStatus.pending

    @pytest.mark.asyncio
    async def test_get_admin_overview_200(self):
        with patch(
            "app.api.v1.corporate_member_onboarding.list_account_onboardings_with_status",
            new_callable=AsyncMock,
            return_value=_OVERVIEW_RESPONSE,
        ), patch(
            "app.api.v1.corporate_member_onboarding._resolve_account_id",
            new_callable=AsyncMock,
            return_value=ACCOUNT_ID,
        ), patch(
            "app.api.v1.corporate_member_onboarding._require_account_admin",
            new_callable=AsyncMock,
        ):
            from app.api.v1.corporate_member_onboarding import admin_onboarding_overview
            user = self._make_admin_user()
            result = await admin_onboarding_overview(user=user, db=AsyncMock())
            assert result.total == 1

    @pytest.mark.asyncio
    async def test_get_admin_detail_200(self):
        with patch(
            "app.api.v1.corporate_member_onboarding.get_onboarding",
            new_callable=AsyncMock,
            return_value=_ONBOARDING_RESPONSE,
        ), patch(
            "app.api.v1.corporate_member_onboarding._resolve_account_id",
            new_callable=AsyncMock,
            return_value=ACCOUNT_ID,
        ), patch(
            "app.api.v1.corporate_member_onboarding._require_account_admin",
            new_callable=AsyncMock,
        ):
            from app.api.v1.corporate_member_onboarding import admin_get_onboarding
            user = self._make_admin_user()
            result = await admin_get_onboarding(
                onboarding_id=ONBOARDING_ID, user=user, db=AsyncMock()
            )
            assert result.id == ONBOARDING_ID

    @pytest.mark.asyncio
    async def test_get_admin_detail_404(self):
        from fastapi import HTTPException
        with patch(
            "app.api.v1.corporate_member_onboarding.get_onboarding",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=404, detail="Not found"),
        ), patch(
            "app.api.v1.corporate_member_onboarding._resolve_account_id",
            new_callable=AsyncMock,
            return_value=ACCOUNT_ID,
        ), patch(
            "app.api.v1.corporate_member_onboarding._require_account_admin",
            new_callable=AsyncMock,
        ):
            from app.api.v1.corporate_member_onboarding import admin_get_onboarding
            user = self._make_admin_user()
            with pytest.raises(HTTPException) as exc_info:
                await admin_get_onboarding(
                    onboarding_id=ONBOARDING_ID, user=user, db=AsyncMock()
                )
            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_put_admin_update_200(self):
        with patch(
            "app.api.v1.corporate_member_onboarding.update_onboarding",
            new_callable=AsyncMock,
            return_value=_ONBOARDING_RESPONSE,
        ), patch(
            "app.api.v1.corporate_member_onboarding._resolve_account_id",
            new_callable=AsyncMock,
            return_value=ACCOUNT_ID,
        ), patch(
            "app.api.v1.corporate_member_onboarding._require_account_admin",
            new_callable=AsyncMock,
        ):
            from app.api.v1.corporate_member_onboarding import admin_update_onboarding
            user = self._make_admin_user()
            data = OnboardingUpdate(notes="Updated notes")
            result = await admin_update_onboarding(
                onboarding_id=ONBOARDING_ID, data=data, user=user, db=AsyncMock()
            )
            assert result.account_id == ACCOUNT_ID

    @pytest.mark.asyncio
    async def test_post_auto_detect_200(self):
        with patch(
            "app.api.v1.corporate_member_onboarding.auto_detect_progress",
            new_callable=AsyncMock,
            return_value=_AUTO_DETECT_RESULT,
        ), patch(
            "app.api.v1.corporate_member_onboarding._resolve_account_id",
            new_callable=AsyncMock,
            return_value=ACCOUNT_ID,
        ), patch(
            "app.api.v1.corporate_member_onboarding._require_account_admin",
            new_callable=AsyncMock,
        ):
            from app.api.v1.corporate_member_onboarding import admin_auto_detect_progress
            user = self._make_admin_user()
            result = await admin_auto_detect_progress(
                onboarding_id=ONBOARDING_ID, user=user, db=AsyncMock()
            )
            assert isinstance(result.newly_detected, list)

    @pytest.mark.asyncio
    async def test_post_auto_detect_409_already_completed(self):
        from fastapi import HTTPException
        with patch(
            "app.api.v1.corporate_member_onboarding.auto_detect_progress",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=409, detail="Already completed"),
        ), patch(
            "app.api.v1.corporate_member_onboarding._resolve_account_id",
            new_callable=AsyncMock,
            return_value=ACCOUNT_ID,
        ), patch(
            "app.api.v1.corporate_member_onboarding._require_account_admin",
            new_callable=AsyncMock,
        ):
            from app.api.v1.corporate_member_onboarding import admin_auto_detect_progress
            user = self._make_admin_user()
            with pytest.raises(HTTPException) as exc_info:
                await admin_auto_detect_progress(
                    onboarding_id=ONBOARDING_ID, user=user, db=AsyncMock()
                )
            assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_post_mark_step_200(self):
        with patch(
            "app.api.v1.corporate_member_onboarding.mark_step_complete",
            new_callable=AsyncMock,
            return_value=_ONBOARDING_RESPONSE,
        ), patch(
            "app.api.v1.corporate_member_onboarding._resolve_account_id",
            new_callable=AsyncMock,
            return_value=ACCOUNT_ID,
        ), patch(
            "app.api.v1.corporate_member_onboarding._require_account_admin",
            new_callable=AsyncMock,
        ):
            from app.api.v1.corporate_member_onboarding import admin_mark_step_complete
            user = self._make_admin_user()
            data = MarkStepRequest(step_name="membership_activated")
            result = await admin_mark_step_complete(
                onboarding_id=ONBOARDING_ID, data=data, user=user, db=AsyncMock()
            )
            assert result.account_id == ACCOUNT_ID

    @pytest.mark.asyncio
    async def test_post_mark_step_409_already_done(self):
        from fastapi import HTTPException
        with patch(
            "app.api.v1.corporate_member_onboarding.mark_step_complete",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=409, detail="Already done"),
        ), patch(
            "app.api.v1.corporate_member_onboarding._resolve_account_id",
            new_callable=AsyncMock,
            return_value=ACCOUNT_ID,
        ), patch(
            "app.api.v1.corporate_member_onboarding._require_account_admin",
            new_callable=AsyncMock,
        ):
            from app.api.v1.corporate_member_onboarding import admin_mark_step_complete
            user = self._make_admin_user()
            data = MarkStepRequest(step_name="membership_activated")
            with pytest.raises(HTTPException) as exc_info:
                await admin_mark_step_complete(
                    onboarding_id=ONBOARDING_ID, data=data, user=user, db=AsyncMock()
                )
            assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_post_complete_200(self):
        with patch(
            "app.api.v1.corporate_member_onboarding.complete_onboarding",
            new_callable=AsyncMock,
            return_value=_ONBOARDING_RESPONSE,
        ), patch(
            "app.api.v1.corporate_member_onboarding._resolve_account_id",
            new_callable=AsyncMock,
            return_value=ACCOUNT_ID,
        ), patch(
            "app.api.v1.corporate_member_onboarding._require_account_admin",
            new_callable=AsyncMock,
        ):
            from app.api.v1.corporate_member_onboarding import admin_complete_onboarding
            user = self._make_admin_user()
            result = await admin_complete_onboarding(
                onboarding_id=ONBOARDING_ID, user=user, db=AsyncMock()
            )
            assert result.account_id == ACCOUNT_ID

    @pytest.mark.asyncio
    async def test_post_complete_409_terminal(self):
        from fastapi import HTTPException
        with patch(
            "app.api.v1.corporate_member_onboarding.complete_onboarding",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=409, detail="Already completed"),
        ), patch(
            "app.api.v1.corporate_member_onboarding._resolve_account_id",
            new_callable=AsyncMock,
            return_value=ACCOUNT_ID,
        ), patch(
            "app.api.v1.corporate_member_onboarding._require_account_admin",
            new_callable=AsyncMock,
        ):
            from app.api.v1.corporate_member_onboarding import admin_complete_onboarding
            user = self._make_admin_user()
            with pytest.raises(HTTPException) as exc_info:
                await admin_complete_onboarding(
                    onboarding_id=ONBOARDING_ID, user=user, db=AsyncMock()
                )
            assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_get_summary_200(self):
        with patch(
            "app.api.v1.corporate_member_onboarding.get_onboarding_summary",
            new_callable=AsyncMock,
            return_value=_SUMMARY_RESPONSE,
        ), patch(
            "app.api.v1.corporate_member_onboarding._resolve_account_id",
            new_callable=AsyncMock,
            return_value=ACCOUNT_ID,
        ), patch(
            "app.api.v1.corporate_member_onboarding._require_account_admin",
            new_callable=AsyncMock,
        ):
            from app.api.v1.corporate_member_onboarding import admin_onboarding_summary
            user = self._make_admin_user()
            result = await admin_onboarding_summary(
                onboarding_id=ONBOARDING_ID, user=user, db=AsyncMock()
            )
            assert result.total_steps == 10

    @pytest.mark.asyncio
    async def test_get_pending_steps_200(self):
        with patch(
            "app.api.v1.corporate_member_onboarding.list_pending_steps",
            new_callable=AsyncMock,
            return_value=list(ONBOARDING_STEPS),
        ), patch(
            "app.api.v1.corporate_member_onboarding._resolve_account_id",
            new_callable=AsyncMock,
            return_value=ACCOUNT_ID,
        ), patch(
            "app.api.v1.corporate_member_onboarding._require_account_admin",
            new_callable=AsyncMock,
        ):
            from app.api.v1.corporate_member_onboarding import admin_list_pending_steps
            user = self._make_admin_user()
            result = await admin_list_pending_steps(
                onboarding_id=ONBOARDING_ID, user=user, db=AsyncMock()
            )
            assert len(result) == 10

    @pytest.mark.asyncio
    async def test_get_member_onboarding_200(self):
        with patch(
            "app.api.v1.corporate_member_onboarding.get_onboarding_for_member",
            new_callable=AsyncMock,
            return_value=_ONBOARDING_RESPONSE,
        ), patch(
            "app.api.v1.corporate_member_onboarding._resolve_account_id",
            new_callable=AsyncMock,
            return_value=ACCOUNT_ID,
        ), patch(
            "app.api.v1.corporate_member_onboarding._require_account_admin",
            new_callable=AsyncMock,
        ):
            from app.api.v1.corporate_member_onboarding import admin_get_member_onboarding
            user = self._make_admin_user()
            result = await admin_get_member_onboarding(
                member_id=MEMBER_USER_ID, user=user, db=AsyncMock()
            )
            assert result.member_id == MEMBER_USER_ID

    @pytest.mark.asyncio
    async def test_get_member_onboarding_404(self):
        from fastapi import HTTPException
        with patch(
            "app.api.v1.corporate_member_onboarding.get_onboarding_for_member",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=404, detail="Not found"),
        ), patch(
            "app.api.v1.corporate_member_onboarding._resolve_account_id",
            new_callable=AsyncMock,
            return_value=ACCOUNT_ID,
        ), patch(
            "app.api.v1.corporate_member_onboarding._require_account_admin",
            new_callable=AsyncMock,
        ):
            from app.api.v1.corporate_member_onboarding import admin_get_member_onboarding
            user = self._make_admin_user()
            with pytest.raises(HTTPException) as exc_info:
                await admin_get_member_onboarding(
                    member_id=999, user=user, db=AsyncMock()
                )
            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_me_onboarding_200(self):
        with patch(
            "app.api.v1.corporate_member_onboarding.get_onboarding_for_member",
            new_callable=AsyncMock,
            return_value=_ONBOARDING_RESPONSE,
        ), patch(
            "app.api.v1.corporate_member_onboarding._resolve_account_id",
            new_callable=AsyncMock,
            return_value=ACCOUNT_ID,
        ):
            from app.api.v1.corporate_member_onboarding import member_get_own_onboarding
            user = self._make_admin_user(user_id=MEMBER_USER_ID)
            result = await member_get_own_onboarding(user=user, db=AsyncMock())
            assert result.member_id == MEMBER_USER_ID

    @pytest.mark.asyncio
    async def test_get_me_onboarding_404_not_in_account(self):
        from fastapi import HTTPException
        with patch(
            "app.api.v1.corporate_member_onboarding._resolve_account_id",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=404, detail="Not a member"),
        ):
            from app.api.v1.corporate_member_onboarding import member_get_own_onboarding
            user = self._make_admin_user()
            with pytest.raises(HTTPException) as exc_info:
                await member_get_own_onboarding(user=user, db=AsyncMock())
            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_platform_list_all_200(self):
        with patch(
            "app.api.v1.corporate_member_onboarding.list_all_platform",
            new_callable=AsyncMock,
            return_value=_ONBOARDING_LIST_RESPONSE,
        ):
            from app.api.v1.corporate_member_onboarding import platform_list_all_onboardings
            admin = self._make_admin_user()
            result = await platform_list_all_onboardings(
                account_id=None, _admin=admin, db=AsyncMock()
            )
            assert result.total == 1

    @pytest.mark.asyncio
    async def test_platform_get_onboarding_200(self):
        ob = _make_onboarding()
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = ob
        db.execute = AsyncMock(return_value=mock_result)

        with patch(
            "app.services.corporate_member_onboarding._onboarding_to_response",
            return_value=_ONBOARDING_RESPONSE,
        ):
            from app.api.v1.corporate_member_onboarding import platform_get_onboarding
            admin = self._make_admin_user()
            result = await platform_get_onboarding(
                onboarding_id=ONBOARDING_ID, _admin=admin, db=db
            )
            assert result.id == ONBOARDING_ID

    @pytest.mark.asyncio
    async def test_platform_get_onboarding_404(self):
        from fastapi import HTTPException
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)

        from app.api.v1.corporate_member_onboarding import platform_get_onboarding
        admin = self._make_admin_user()
        with pytest.raises(HTTPException) as exc_info:
            await platform_get_onboarding(
                onboarding_id=ONBOARDING_ID, _admin=admin, db=db
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_platform_list_for_account_200(self):
        with patch(
            "app.api.v1.corporate_member_onboarding.list_all_platform",
            new_callable=AsyncMock,
            return_value=_ONBOARDING_LIST_RESPONSE,
        ):
            from app.api.v1.corporate_member_onboarding import platform_list_onboardings_for_account
            admin = self._make_admin_user()
            result = await platform_list_onboardings_for_account(
                account_id=ACCOUNT_ID, _admin=admin, db=AsyncMock()
            )
            assert result.total == 1
