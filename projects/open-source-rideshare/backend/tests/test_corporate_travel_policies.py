"""Tests for the Corporate Travel Policy & Acknowledgement feature.

Service layer (async, mocked DB):
  1.  create_policy — creates inactive draft policy
  2.  create_policy — sets created_by_id from caller
  3.  get_policy — returns policy when found
  4.  get_policy — 404 when not found
  5.  get_policy — 404 when policy belongs to different account
  6.  get_active_policy — returns active policy when found
  7.  get_active_policy — returns None when no active policy
  8.  list_policies — returns all policies newest first
  9.  list_policies — filter is_active=True returns only active
  10. list_policies — filter is_active=False returns only inactive
  11. update_policy — partial update on draft policy
  12. update_policy — 404 when policy not found
  13. update_policy — 409 when policy is active
  14. update_policy — only supplied fields updated (exclude_unset)
  15. activate_policy — activates a draft policy
  16. activate_policy — deactivates previously active policy on activation
  17. activate_policy — 404 when policy not found
  18. activate_policy — 409 when policy is already active
  19. deactivate_policy — deactivates an active policy
  20. deactivate_policy — 404 when policy not found
  21. deactivate_policy — 409 when policy is already inactive
  22. delete_policy — deletes an inactive policy
  23. delete_policy — 404 when policy not found
  24. delete_policy — 409 when policy is active
  25. acknowledge_policy — creates acknowledgement for active policy
  26. acknowledge_policy — 404 when policy not found
  27. acknowledge_policy — 404 when policy is not active
  28. acknowledge_policy — 409 when already acknowledged
  29. get_member_acknowledgement_status — acknowledged member, active policy
  30. get_member_acknowledgement_status — unacknowledged member, active policy
  31. get_member_acknowledgement_status — no active policy returns policy_id=None
  32. get_member_acknowledgement_status — requires_acknowledgement propagated
  33. get_acknowledgement_summary — returns all acks for policy
  34. get_acknowledgement_summary — 404 when policy not found
  35. get_acknowledgement_summary — empty list when no acks
  36. list_all_platform — returns all policies without filter
  37. list_all_platform — filters by account_id

Schema validation:
  38. TravelPolicyCreate — valid data accepted
  39. TravelPolicyCreate — blank title rejected
  40. TravelPolicyCreate — content too short rejected
  41. TravelPolicyCreate — blank version_number rejected
  42. TravelPolicyCreate — effective_date optional
  43. TravelPolicyUpdate — all fields optional
  44. TravelPolicyUpdate — blank title rejected
  45. TravelPolicyUpdate — content too short rejected
  46. TravelPolicyResponse — from_attributes construction
  47. AcknowledgementResponse — from_attributes construction
  48. MemberAcknowledgementStatus — all fields present
  49. AcknowledgementSummary — total_acknowledged + acknowledgements fields

API layer (service functions patched):
  50. GET active policy — 200 member gets active policy
  51. GET active policy — 200 returns null when no active policy
  52. GET active policy — 404 when user not in corporate account
  53. GET my-status — 200 member gets own acknowledgement status
  54. POST acknowledge — 201 member acknowledges policy
  55. POST acknowledge — 409 when already acknowledged
  56. POST create — 201 admin creates draft policy
  57. POST create — 403 non-admin cannot create
  58. POST create — 422 validation error for short content
  59. GET list — 200 admin lists all versions
  60. GET list — 403 non-admin cannot list
  61. GET list — is_active query param passed through
  62. GET {policy_id} — 200 admin gets specific policy
  63. GET {policy_id} — 403 non-admin cannot get
  64. PUT {policy_id} — 200 admin updates draft policy
  65. PUT {policy_id} — 403 non-admin cannot update
  66. POST activate — 200 admin activates policy
  67. POST activate — 409 when already active
  68. POST deactivate — 200 admin deactivates policy
  69. DELETE {policy_id} — 204 admin deletes draft
  70. DELETE {policy_id} — 409 when active
  71. GET acknowledgements — 200 admin gets ack summary
  72. GET acknowledgements — 403 non-admin cannot access
  73. GET platform all — 200 platform-admin list all
  74. GET platform account — 200 platform-admin list for account
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.corporate_travel_policy import (
    CorporatePolicyAcknowledgement,
    CorporateTravelPolicy,
)
from app.schemas.corporate_travel_policy import (
    AcknowledgementResponse,
    AcknowledgementSummary,
    MemberAcknowledgementStatus,
    TravelPolicyCreate,
    TravelPolicyListResponse,
    TravelPolicyResponse,
    TravelPolicyUpdate,
)
from app.services.corporate_travel_policy import (
    acknowledge_policy,
    activate_policy,
    create_policy,
    deactivate_policy,
    delete_policy,
    get_acknowledgement_summary,
    get_active_policy,
    get_member_acknowledgement_status,
    get_policy,
    list_all_platform,
    list_policies,
    update_policy,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

NOW = datetime(2026, 4, 16, 0, 0, 0, tzinfo=timezone.utc)

ACCOUNT_ID = 10
MEMBER_ID = 20
ADMIN_ID = 21
POLICY_ID = 1
ACK_ID = 5


def _make_policy(
    id: int = POLICY_ID,
    account_id: int = ACCOUNT_ID,
    title: str = "Q2 2026 Travel Policy",
    content: str = "All business travel must be approved in advance by your manager.",
    version_number: str = "1",
    is_active: bool = False,
    requires_acknowledgement: bool = True,
    effective_date=None,
    created_by_id: int | None = ADMIN_ID,
) -> CorporateTravelPolicy:
    policy = CorporateTravelPolicy()
    policy.id = id
    policy.account_id = account_id
    policy.title = title
    policy.content = content
    policy.version_number = version_number
    policy.is_active = is_active
    policy.requires_acknowledgement = requires_acknowledgement
    policy.effective_date = effective_date
    policy.created_by_id = created_by_id
    policy.created_at = NOW
    policy.updated_at = NOW
    return policy


def _make_active_policy(**kwargs) -> CorporateTravelPolicy:
    return _make_policy(is_active=True, **kwargs)


def _make_ack(
    id: int = ACK_ID,
    policy_id: int = POLICY_ID,
    member_id: int = MEMBER_ID,
    account_id: int = ACCOUNT_ID,
) -> CorporatePolicyAcknowledgement:
    ack = CorporatePolicyAcknowledgement()
    ack.id = id
    ack.policy_id = policy_id
    ack.member_id = member_id
    ack.account_id = account_id
    ack.acknowledged_at = NOW
    return ack


def _make_policy_response(policy: CorporateTravelPolicy) -> TravelPolicyResponse:
    return TravelPolicyResponse(
        id=policy.id,
        account_id=policy.account_id,
        title=policy.title,
        content=policy.content,
        version_number=policy.version_number,
        is_active=policy.is_active,
        requires_acknowledgement=policy.requires_acknowledgement,
        effective_date=policy.effective_date,
        created_by_id=policy.created_by_id,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
    )


def _db_returning(row):
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    db.execute.return_value = result
    return db


def _db_returning_all(rows):
    db = AsyncMock()
    result = MagicMock()
    scalar_result = MagicMock()
    scalar_result.all.return_value = rows
    result.scalars.return_value = scalar_result
    db.execute.return_value = result
    return db


# ---------------------------------------------------------------------------
# Service layer tests — create_policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_policy_creates_inactive_draft():
    """create_policy creates a new policy with is_active=False."""
    db = AsyncMock()
    db.add = MagicMock()

    async def _refresh(obj):
        obj.id = POLICY_ID
        obj.created_at = NOW
        obj.updated_at = NOW

    db.refresh = AsyncMock(side_effect=_refresh)

    data = TravelPolicyCreate(
        title="Q2 2026 Travel Policy",
        content="All business travel must be approved in advance.",
        version_number="1",
    )
    result = await create_policy(db, ACCOUNT_ID, ADMIN_ID, data)

    db.add.assert_called_once()
    db.commit.assert_called_once()
    assert result.is_active is False


@pytest.mark.asyncio
async def test_create_policy_sets_created_by_id():
    """create_policy sets created_by_id from the caller argument."""
    db = AsyncMock()
    added_policy = None

    def _capture_add(obj):
        nonlocal added_policy
        added_policy = obj

    # db.add is called synchronously in the service layer
    db.add = MagicMock(side_effect=_capture_add)

    async def _refresh(obj):
        obj.id = POLICY_ID
        obj.created_at = NOW
        obj.updated_at = NOW

    db.refresh = AsyncMock(side_effect=_refresh)

    data = TravelPolicyCreate(
        title="Policy Title",
        content="Full policy content here.",
    )
    await create_policy(db, ACCOUNT_ID, ADMIN_ID, data)
    assert added_policy is not None
    assert added_policy.created_by_id == ADMIN_ID


# ---------------------------------------------------------------------------
# Service layer tests — get_policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_policy_returns_policy_when_found():
    """get_policy returns the policy response when found."""
    policy = _make_policy()
    db = _db_returning(policy)
    result = await get_policy(db, ACCOUNT_ID, POLICY_ID)
    assert result.id == POLICY_ID
    assert result.account_id == ACCOUNT_ID


@pytest.mark.asyncio
async def test_get_policy_raises_404_when_not_found():
    """get_policy raises HTTP 404 when policy is not found."""
    from fastapi import HTTPException

    db = _db_returning(None)
    with pytest.raises(HTTPException) as exc:
        await get_policy(db, ACCOUNT_ID, POLICY_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_policy_404_for_different_account():
    """get_policy raises 404 when the policy belongs to a different account."""
    from fastapi import HTTPException

    db = _db_returning(None)
    with pytest.raises(HTTPException) as exc:
        await get_policy(db, account_id=999, policy_id=POLICY_ID)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Service layer tests — get_active_policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_active_policy_returns_active_policy():
    """get_active_policy returns the active policy for the account."""
    policy = _make_active_policy()
    db = _db_returning(policy)
    result = await get_active_policy(db, ACCOUNT_ID)
    assert result is not None
    assert result.is_active is True


@pytest.mark.asyncio
async def test_get_active_policy_returns_none_when_no_active():
    """get_active_policy returns None when no active policy exists."""
    db = _db_returning(None)
    result = await get_active_policy(db, ACCOUNT_ID)
    assert result is None


# ---------------------------------------------------------------------------
# Service layer tests — list_policies
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_policies_returns_all():
    """list_policies returns all policies for the account."""
    policies = [_make_policy(id=1), _make_policy(id=2, is_active=True)]
    db = _db_returning_all(policies)
    result = await list_policies(db, ACCOUNT_ID)
    assert result.total == 2
    assert len(result.items) == 2


@pytest.mark.asyncio
async def test_list_policies_filter_active():
    """list_policies with is_active=True returns only active policies."""
    active = _make_active_policy(id=1)
    db = _db_returning_all([active])
    result = await list_policies(db, ACCOUNT_ID, is_active=True)
    assert result.total == 1
    assert result.items[0].is_active is True


@pytest.mark.asyncio
async def test_list_policies_filter_inactive():
    """list_policies with is_active=False returns only inactive policies."""
    draft = _make_policy(id=2, is_active=False)
    db = _db_returning_all([draft])
    result = await list_policies(db, ACCOUNT_ID, is_active=False)
    assert result.total == 1
    assert result.items[0].is_active is False


# ---------------------------------------------------------------------------
# Service layer tests — update_policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_policy_partial_update_on_draft():
    """update_policy writes only the supplied fields."""
    policy = _make_policy(title="Old Title")
    db = _db_returning(policy)
    data = TravelPolicyUpdate(title="New Title")
    result = await update_policy(db, ACCOUNT_ID, POLICY_ID, data)
    assert policy.title == "New Title"
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_update_policy_404_when_not_found():
    """update_policy raises 404 when the policy is not found."""
    from fastapi import HTTPException

    db = _db_returning(None)
    data = TravelPolicyUpdate(title="New Title")
    with pytest.raises(HTTPException) as exc:
        await update_policy(db, ACCOUNT_ID, POLICY_ID, data)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_policy_409_when_active():
    """update_policy raises 409 when the policy is currently active."""
    from fastapi import HTTPException

    policy = _make_active_policy()
    db = _db_returning(policy)
    data = TravelPolicyUpdate(title="New Title")
    with pytest.raises(HTTPException) as exc:
        await update_policy(db, ACCOUNT_ID, POLICY_ID, data)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_update_policy_only_supplied_fields():
    """update_policy does not overwrite fields not supplied in the request."""
    policy = _make_policy(title="Original", version_number="1")
    db = _db_returning(policy)
    # Only title is supplied; version_number should stay "1"
    data = TravelPolicyUpdate(title="Updated")
    await update_policy(db, ACCOUNT_ID, POLICY_ID, data)
    assert policy.title == "Updated"
    assert policy.version_number == "1"


# ---------------------------------------------------------------------------
# Service layer tests — activate_policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_activate_policy_activates_draft():
    """activate_policy sets is_active=True on a draft policy."""
    policy = _make_policy(is_active=False)

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        # First call: get the target policy; second call: get currently active
        if call_count == 1:
            result.scalar_one_or_none.return_value = policy
        else:
            result.scalar_one_or_none.return_value = None
        return result

    db = AsyncMock()
    db.execute.side_effect = _side_effect

    result = await activate_policy(db, ACCOUNT_ID, POLICY_ID)
    assert policy.is_active is True
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_activate_policy_deactivates_previous_active():
    """activate_policy deactivates the previously active policy."""
    old_active = _make_active_policy(id=99)
    new_policy = _make_policy(id=POLICY_ID, is_active=False)

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = new_policy
        else:
            result.scalar_one_or_none.return_value = old_active
        return result

    db = AsyncMock()
    db.execute.side_effect = _side_effect

    await activate_policy(db, ACCOUNT_ID, POLICY_ID)
    assert old_active.is_active is False
    assert new_policy.is_active is True


@pytest.mark.asyncio
async def test_activate_policy_404_when_not_found():
    """activate_policy raises 404 when the policy is not found."""
    from fastapi import HTTPException

    db = _db_returning(None)
    with pytest.raises(HTTPException) as exc:
        await activate_policy(db, ACCOUNT_ID, POLICY_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_activate_policy_409_when_already_active():
    """activate_policy raises 409 when the policy is already active."""
    from fastapi import HTTPException

    policy = _make_active_policy()
    db = _db_returning(policy)
    with pytest.raises(HTTPException) as exc:
        await activate_policy(db, ACCOUNT_ID, POLICY_ID)
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# Service layer tests — deactivate_policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deactivate_policy_deactivates_active():
    """deactivate_policy sets is_active=False on an active policy."""
    policy = _make_active_policy()
    db = _db_returning(policy)
    result = await deactivate_policy(db, ACCOUNT_ID, POLICY_ID)
    assert policy.is_active is False
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_deactivate_policy_404_when_not_found():
    """deactivate_policy raises 404 when the policy is not found."""
    from fastapi import HTTPException

    db = _db_returning(None)
    with pytest.raises(HTTPException) as exc:
        await deactivate_policy(db, ACCOUNT_ID, POLICY_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_deactivate_policy_409_when_already_inactive():
    """deactivate_policy raises 409 when the policy is already inactive."""
    from fastapi import HTTPException

    policy = _make_policy(is_active=False)
    db = _db_returning(policy)
    with pytest.raises(HTTPException) as exc:
        await deactivate_policy(db, ACCOUNT_ID, POLICY_ID)
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# Service layer tests — delete_policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_policy_deletes_inactive():
    """delete_policy hard-deletes an inactive policy."""
    policy = _make_policy(is_active=False)
    db = _db_returning(policy)
    await delete_policy(db, ACCOUNT_ID, POLICY_ID)
    db.delete.assert_called_once_with(policy)
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_delete_policy_404_when_not_found():
    """delete_policy raises 404 when the policy is not found."""
    from fastapi import HTTPException

    db = _db_returning(None)
    with pytest.raises(HTTPException) as exc:
        await delete_policy(db, ACCOUNT_ID, POLICY_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_policy_409_when_active():
    """delete_policy raises 409 when the policy is active."""
    from fastapi import HTTPException

    policy = _make_active_policy()
    db = _db_returning(policy)
    with pytest.raises(HTTPException) as exc:
        await delete_policy(db, ACCOUNT_ID, POLICY_ID)
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# Service layer tests — acknowledge_policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acknowledge_policy_creates_acknowledgement():
    """acknowledge_policy creates an acknowledgement record for an active policy."""
    active_policy = _make_active_policy()
    ack = _make_ack()

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            # get policy
            result.scalar_one_or_none.return_value = active_policy
        else:
            # check for existing ack — none found
            result.scalar_one_or_none.return_value = None
        return result

    db = AsyncMock()
    db.execute.side_effect = _side_effect
    db.add = MagicMock()

    async def _refresh(obj):
        obj.id = ACK_ID
        obj.acknowledged_at = NOW

    db.refresh = AsyncMock(side_effect=_refresh)

    await acknowledge_policy(db, ACCOUNT_ID, MEMBER_ID, POLICY_ID)
    db.add.assert_called_once()
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_acknowledge_policy_404_when_not_found():
    """acknowledge_policy raises 404 when the policy is not found."""
    from fastapi import HTTPException

    db = _db_returning(None)
    with pytest.raises(HTTPException) as exc:
        await acknowledge_policy(db, ACCOUNT_ID, MEMBER_ID, POLICY_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_acknowledge_policy_404_when_not_active():
    """acknowledge_policy raises 404 when the policy exists but is not active."""
    from fastapi import HTTPException

    inactive = _make_policy(is_active=False)
    db = _db_returning(inactive)
    with pytest.raises(HTTPException) as exc:
        await acknowledge_policy(db, ACCOUNT_ID, MEMBER_ID, POLICY_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_acknowledge_policy_409_when_already_acknowledged():
    """acknowledge_policy raises 409 when the member has already acknowledged."""
    from fastapi import HTTPException

    active_policy = _make_active_policy()
    existing_ack = _make_ack()

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = active_policy
        else:
            result.scalar_one_or_none.return_value = existing_ack
        return result

    db = AsyncMock()
    db.execute.side_effect = _side_effect

    with pytest.raises(HTTPException) as exc:
        await acknowledge_policy(db, ACCOUNT_ID, MEMBER_ID, POLICY_ID)
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# Service layer tests — get_member_acknowledgement_status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_member_ack_status_acknowledged():
    """get_member_acknowledgement_status returns has_acknowledged=True when acked."""
    active_policy = _make_active_policy()
    ack = _make_ack()

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = active_policy
        else:
            result.scalar_one_or_none.return_value = ack
        return result

    db = AsyncMock()
    db.execute.side_effect = _side_effect

    status_obj = await get_member_acknowledgement_status(db, ACCOUNT_ID, MEMBER_ID)
    assert status_obj.has_acknowledged is True
    assert status_obj.policy_id == POLICY_ID
    assert status_obj.acknowledged_at == NOW


@pytest.mark.asyncio
async def test_get_member_ack_status_not_acknowledged():
    """get_member_acknowledgement_status returns has_acknowledged=False when no ack."""
    active_policy = _make_active_policy()

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = active_policy
        else:
            result.scalar_one_or_none.return_value = None
        return result

    db = AsyncMock()
    db.execute.side_effect = _side_effect

    status_obj = await get_member_acknowledgement_status(db, ACCOUNT_ID, MEMBER_ID)
    assert status_obj.has_acknowledged is False
    assert status_obj.acknowledged_at is None


@pytest.mark.asyncio
async def test_get_member_ack_status_no_active_policy():
    """get_member_acknowledgement_status returns policy_id=None when no active policy."""
    db = _db_returning(None)
    status_obj = await get_member_acknowledgement_status(db, ACCOUNT_ID, MEMBER_ID)
    assert status_obj.policy_id is None
    assert status_obj.has_acknowledged is False
    assert status_obj.requires_acknowledgement is False


@pytest.mark.asyncio
async def test_get_member_ack_status_propagates_requires_acknowledgement():
    """get_member_acknowledgement_status propagates requires_acknowledgement from policy."""
    active_policy = _make_active_policy(requires_acknowledgement=False)

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = active_policy
        else:
            result.scalar_one_or_none.return_value = None
        return result

    db = AsyncMock()
    db.execute.side_effect = _side_effect

    status_obj = await get_member_acknowledgement_status(db, ACCOUNT_ID, MEMBER_ID)
    assert status_obj.requires_acknowledgement is False


# ---------------------------------------------------------------------------
# Service layer tests — get_acknowledgement_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_acknowledgement_summary_returns_all():
    """get_acknowledgement_summary returns all acknowledgements for a policy."""
    policy = _make_policy()
    acks = [_make_ack(id=1, member_id=20), _make_ack(id=2, member_id=21)]

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            # get_policy_or_404
            result.scalar_one_or_none.return_value = policy
        else:
            # list acknowledgements
            scalar_result = MagicMock()
            scalar_result.all.return_value = acks
            result.scalars.return_value = scalar_result
        return result

    db = AsyncMock()
    db.execute.side_effect = _side_effect

    summary = await get_acknowledgement_summary(db, ACCOUNT_ID, POLICY_ID)
    assert summary.policy_id == POLICY_ID
    assert summary.total_acknowledged == 2
    assert len(summary.acknowledgements) == 2


@pytest.mark.asyncio
async def test_get_acknowledgement_summary_404_when_not_found():
    """get_acknowledgement_summary raises 404 when policy is not found."""
    from fastapi import HTTPException

    db = _db_returning(None)
    with pytest.raises(HTTPException) as exc:
        await get_acknowledgement_summary(db, ACCOUNT_ID, POLICY_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_acknowledgement_summary_empty_when_no_acks():
    """get_acknowledgement_summary returns empty list when no acks exist."""
    policy = _make_policy()

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = policy
        else:
            scalar_result = MagicMock()
            scalar_result.all.return_value = []
            result.scalars.return_value = scalar_result
        return result

    db = AsyncMock()
    db.execute.side_effect = _side_effect

    summary = await get_acknowledgement_summary(db, ACCOUNT_ID, POLICY_ID)
    assert summary.total_acknowledged == 0
    assert summary.acknowledgements == []


# ---------------------------------------------------------------------------
# Service layer tests — list_all_platform
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_all_platform_returns_all():
    """list_all_platform returns all policies without account filter."""
    policies = [_make_policy(id=1, account_id=10), _make_policy(id=2, account_id=20)]
    db = _db_returning_all(policies)
    result = await list_all_platform(db)
    assert result.total == 2


@pytest.mark.asyncio
async def test_list_all_platform_filters_by_account():
    """list_all_platform with account_id filter returns only that account's policies."""
    policies = [_make_policy(id=1, account_id=10)]
    db = _db_returning_all(policies)
    result = await list_all_platform(db, account_id=10)
    assert result.total == 1
    assert result.items[0].account_id == 10


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


def test_policy_create_valid():
    """TravelPolicyCreate accepts valid data."""
    data = TravelPolicyCreate(
        title="Q2 Policy",
        content="All travel must be pre-approved.",
        version_number="2",
        requires_acknowledgement=True,
    )
    assert data.title == "Q2 Policy"
    assert data.version_number == "2"


def test_policy_create_blank_title_rejected():
    """TravelPolicyCreate rejects a blank title."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        TravelPolicyCreate(title="   ", content="Valid content here.")


def test_policy_create_content_too_short():
    """TravelPolicyCreate rejects content shorter than 10 chars."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        TravelPolicyCreate(title="Title", content="Short")


def test_policy_create_blank_version_number_rejected():
    """TravelPolicyCreate rejects a blank version_number."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        TravelPolicyCreate(
            title="Title", content="Valid content here.", version_number="  "
        )


def test_policy_create_effective_date_optional():
    """TravelPolicyCreate allows effective_date to be None."""
    data = TravelPolicyCreate(title="T", content="Valid content here.")
    assert data.effective_date is None


def test_policy_update_all_fields_optional():
    """TravelPolicyUpdate accepts empty update (all fields optional)."""
    data = TravelPolicyUpdate()
    assert data.model_dump(exclude_unset=True) == {}


def test_policy_update_blank_title_rejected():
    """TravelPolicyUpdate rejects a blank title when supplied."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        TravelPolicyUpdate(title="  ")


def test_policy_update_content_too_short():
    """TravelPolicyUpdate rejects short content when supplied."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        TravelPolicyUpdate(content="Hi")


def test_policy_response_from_attributes():
    """TravelPolicyResponse can be constructed from ORM attributes."""
    policy = _make_policy()
    response = TravelPolicyResponse.model_validate(policy)
    assert response.id == POLICY_ID
    assert response.account_id == ACCOUNT_ID


def test_ack_response_from_attributes():
    """AcknowledgementResponse can be constructed from ORM attributes."""
    ack = _make_ack()
    response = AcknowledgementResponse.model_validate(ack)
    assert response.id == ACK_ID
    assert response.policy_id == POLICY_ID
    assert response.member_id == MEMBER_ID


def test_member_ack_status_fields():
    """MemberAcknowledgementStatus has all required fields."""
    obj = MemberAcknowledgementStatus(
        member_id=MEMBER_ID,
        policy_id=POLICY_ID,
        has_acknowledged=True,
        acknowledged_at=NOW,
        requires_acknowledgement=True,
    )
    assert obj.has_acknowledged is True
    assert obj.acknowledged_at == NOW


def test_ack_summary_fields():
    """AcknowledgementSummary has total_acknowledged and acknowledgements."""
    ack = _make_ack()
    ack_resp = AcknowledgementResponse.model_validate(ack)
    summary = AcknowledgementSummary(
        policy_id=POLICY_ID,
        total_acknowledged=1,
        acknowledgements=[ack_resp],
    )
    assert summary.total_acknowledged == 1
    assert len(summary.acknowledgements) == 1


# ---------------------------------------------------------------------------
# API layer tests
# ---------------------------------------------------------------------------

_ROUTER = "app.api.v1.corporate_travel_policies"


# --- GET active policy ---


@pytest.mark.asyncio
async def test_api_get_active_travel_policy_200():
    """GET active policy returns the active policy."""
    policy_resp = _make_policy_response(_make_active_policy())

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}.get_active_policy", return_value=policy_resp),
    ):
        from app.api.v1.corporate_travel_policies import get_active_travel_policy

        result = await get_active_travel_policy(
            user=MagicMock(id=MEMBER_ID), db=AsyncMock()
        )
    assert result.is_active is True


@pytest.mark.asyncio
async def test_api_get_active_travel_policy_returns_none():
    """GET active policy returns None when no policy is active."""
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}.get_active_policy", return_value=None),
    ):
        from app.api.v1.corporate_travel_policies import get_active_travel_policy

        result = await get_active_travel_policy(
            user=MagicMock(id=MEMBER_ID), db=AsyncMock()
        )
    assert result is None


@pytest.mark.asyncio
async def test_api_get_active_travel_policy_404_no_account():
    """GET active policy raises 404 when user is not in a corporate account."""
    from fastapi import HTTPException

    with patch(
        f"{_ROUTER}._resolve_account_id",
        side_effect=HTTPException(status_code=404, detail="not in account"),
    ):
        from app.api.v1.corporate_travel_policies import get_active_travel_policy

        with pytest.raises(HTTPException) as exc:
            await get_active_travel_policy(
                user=MagicMock(id=MEMBER_ID), db=AsyncMock()
            )
    assert exc.value.status_code == 404


# --- GET my-status ---


@pytest.mark.asyncio
async def test_api_get_my_acknowledgement_status_200():
    """GET my-status returns the member's acknowledgement status."""
    status_obj = MemberAcknowledgementStatus(
        member_id=MEMBER_ID,
        policy_id=POLICY_ID,
        has_acknowledged=False,
        acknowledged_at=None,
        requires_acknowledgement=True,
    )
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(
            f"{_ROUTER}.get_member_acknowledgement_status", return_value=status_obj
        ),
    ):
        from app.api.v1.corporate_travel_policies import get_my_acknowledgement_status

        result = await get_my_acknowledgement_status(
            user=MagicMock(id=MEMBER_ID), db=AsyncMock()
        )
    assert result.has_acknowledged is False
    assert result.requires_acknowledgement is True


# --- POST acknowledge ---


@pytest.mark.asyncio
async def test_api_acknowledge_travel_policy_201():
    """POST acknowledge creates acknowledgement record."""
    ack_resp = AcknowledgementResponse(
        id=ACK_ID,
        policy_id=POLICY_ID,
        member_id=MEMBER_ID,
        account_id=ACCOUNT_ID,
        acknowledged_at=NOW,
    )
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}.acknowledge_policy", return_value=ack_resp),
    ):
        from app.api.v1.corporate_travel_policies import acknowledge_travel_policy

        result = await acknowledge_travel_policy(
            policy_id=POLICY_ID, user=MagicMock(id=MEMBER_ID), db=AsyncMock()
        )
    assert result.id == ACK_ID


@pytest.mark.asyncio
async def test_api_acknowledge_travel_policy_409_duplicate():
    """POST acknowledge raises 409 when member has already acknowledged."""
    from fastapi import HTTPException

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(
            f"{_ROUTER}.acknowledge_policy",
            side_effect=HTTPException(status_code=409, detail="Already acknowledged"),
        ),
    ):
        from app.api.v1.corporate_travel_policies import acknowledge_travel_policy

        with pytest.raises(HTTPException) as exc:
            await acknowledge_travel_policy(
                policy_id=POLICY_ID, user=MagicMock(id=MEMBER_ID), db=AsyncMock()
            )
    assert exc.value.status_code == 409


# --- POST create ---


@pytest.mark.asyncio
async def test_api_create_travel_policy_201():
    """POST create returns newly created draft policy."""
    policy_resp = _make_policy_response(_make_policy())
    data = TravelPolicyCreate(
        title="Q2 Policy",
        content="All travel must be pre-approved by manager.",
    )
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin"),
        patch(f"{_ROUTER}.create_policy", return_value=policy_resp),
    ):
        from app.api.v1.corporate_travel_policies import create_travel_policy

        result = await create_travel_policy(
            data=data, user=MagicMock(id=ADMIN_ID), db=AsyncMock()
        )
    assert result.is_active is False


@pytest.mark.asyncio
async def test_api_create_travel_policy_403_non_admin():
    """POST create raises 403 when non-admin attempts creation."""
    from fastapi import HTTPException

    data = TravelPolicyCreate(
        title="Q2 Policy",
        content="All travel must be pre-approved by manager.",
    )
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(
            f"{_ROUTER}._require_account_admin",
            side_effect=HTTPException(status_code=403, detail="Forbidden"),
        ),
    ):
        from app.api.v1.corporate_travel_policies import create_travel_policy

        with pytest.raises(HTTPException) as exc:
            await create_travel_policy(
                data=data, user=MagicMock(id=MEMBER_ID), db=AsyncMock()
            )
    assert exc.value.status_code == 403


def test_api_create_travel_policy_422_short_content():
    """TravelPolicyCreate raises ValidationError for content too short."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        TravelPolicyCreate(title="Title", content="Short")


# --- GET list ---


@pytest.mark.asyncio
async def test_api_list_travel_policies_200():
    """GET list returns all policy versions."""
    policies_resp = TravelPolicyListResponse(
        items=[_make_policy_response(_make_policy())], total=1
    )
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin"),
        patch(f"{_ROUTER}.list_policies", return_value=policies_resp),
    ):
        from app.api.v1.corporate_travel_policies import list_travel_policies

        result = await list_travel_policies(
            is_active=None, user=MagicMock(id=ADMIN_ID), db=AsyncMock()
        )
    assert result.total == 1


@pytest.mark.asyncio
async def test_api_list_travel_policies_403_non_admin():
    """GET list raises 403 when non-admin attempts access."""
    from fastapi import HTTPException

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(
            f"{_ROUTER}._require_account_admin",
            side_effect=HTTPException(status_code=403, detail="Forbidden"),
        ),
    ):
        from app.api.v1.corporate_travel_policies import list_travel_policies

        with pytest.raises(HTTPException) as exc:
            await list_travel_policies(
                is_active=None, user=MagicMock(id=MEMBER_ID), db=AsyncMock()
            )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_api_list_travel_policies_is_active_param():
    """GET list passes is_active param to service."""
    policies_resp = TravelPolicyListResponse(items=[], total=0)
    mock_list = AsyncMock(return_value=policies_resp)

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin"),
        patch(f"{_ROUTER}.list_policies", new=mock_list),
    ):
        from app.api.v1.corporate_travel_policies import list_travel_policies

        await list_travel_policies(
            is_active=True, user=MagicMock(id=ADMIN_ID), db=AsyncMock()
        )
    _, kwargs = mock_list.call_args
    assert kwargs.get("is_active") is True


# --- GET {policy_id} ---


@pytest.mark.asyncio
async def test_api_get_travel_policy_200():
    """GET {policy_id} returns the policy."""
    policy_resp = _make_policy_response(_make_policy())

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin"),
        patch(f"{_ROUTER}.get_policy", return_value=policy_resp),
    ):
        from app.api.v1.corporate_travel_policies import get_travel_policy

        result = await get_travel_policy(
            policy_id=POLICY_ID, user=MagicMock(id=ADMIN_ID), db=AsyncMock()
        )
    assert result.id == POLICY_ID


@pytest.mark.asyncio
async def test_api_get_travel_policy_403_non_admin():
    """GET {policy_id} raises 403 for non-admin."""
    from fastapi import HTTPException

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(
            f"{_ROUTER}._require_account_admin",
            side_effect=HTTPException(status_code=403, detail="Forbidden"),
        ),
    ):
        from app.api.v1.corporate_travel_policies import get_travel_policy

        with pytest.raises(HTTPException) as exc:
            await get_travel_policy(
                policy_id=POLICY_ID, user=MagicMock(id=MEMBER_ID), db=AsyncMock()
            )
    assert exc.value.status_code == 403


# --- PUT update ---


@pytest.mark.asyncio
async def test_api_update_travel_policy_200():
    """PUT {policy_id} returns updated policy."""
    policy_resp = _make_policy_response(_make_policy(title="Updated"))
    data = TravelPolicyUpdate(title="Updated")

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin"),
        patch(f"{_ROUTER}.update_policy", return_value=policy_resp),
    ):
        from app.api.v1.corporate_travel_policies import update_travel_policy

        result = await update_travel_policy(
            policy_id=POLICY_ID, data=data, user=MagicMock(id=ADMIN_ID), db=AsyncMock()
        )
    assert result.title == "Updated"


@pytest.mark.asyncio
async def test_api_update_travel_policy_403_non_admin():
    """PUT {policy_id} raises 403 for non-admin."""
    from fastapi import HTTPException

    data = TravelPolicyUpdate(title="Updated")

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(
            f"{_ROUTER}._require_account_admin",
            side_effect=HTTPException(status_code=403, detail="Forbidden"),
        ),
    ):
        from app.api.v1.corporate_travel_policies import update_travel_policy

        with pytest.raises(HTTPException) as exc:
            await update_travel_policy(
                policy_id=POLICY_ID,
                data=data,
                user=MagicMock(id=MEMBER_ID),
                db=AsyncMock(),
            )
    assert exc.value.status_code == 403


# --- POST activate ---


@pytest.mark.asyncio
async def test_api_activate_travel_policy_200():
    """POST activate returns active policy."""
    policy_resp = _make_policy_response(_make_active_policy())

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin"),
        patch(f"{_ROUTER}.activate_policy", return_value=policy_resp),
    ):
        from app.api.v1.corporate_travel_policies import activate_travel_policy

        result = await activate_travel_policy(
            policy_id=POLICY_ID, user=MagicMock(id=ADMIN_ID), db=AsyncMock()
        )
    assert result.is_active is True


@pytest.mark.asyncio
async def test_api_activate_travel_policy_409_already_active():
    """POST activate raises 409 when policy is already active."""
    from fastapi import HTTPException

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin"),
        patch(
            f"{_ROUTER}.activate_policy",
            side_effect=HTTPException(status_code=409, detail="Already active"),
        ),
    ):
        from app.api.v1.corporate_travel_policies import activate_travel_policy

        with pytest.raises(HTTPException) as exc:
            await activate_travel_policy(
                policy_id=POLICY_ID, user=MagicMock(id=ADMIN_ID), db=AsyncMock()
            )
    assert exc.value.status_code == 409


# --- POST deactivate ---


@pytest.mark.asyncio
async def test_api_deactivate_travel_policy_200():
    """POST deactivate returns deactivated policy."""
    policy_resp = _make_policy_response(_make_policy(is_active=False))

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin"),
        patch(f"{_ROUTER}.deactivate_policy", return_value=policy_resp),
    ):
        from app.api.v1.corporate_travel_policies import deactivate_travel_policy

        result = await deactivate_travel_policy(
            policy_id=POLICY_ID, user=MagicMock(id=ADMIN_ID), db=AsyncMock()
        )
    assert result.is_active is False


# --- DELETE ---


@pytest.mark.asyncio
async def test_api_delete_travel_policy_204():
    """DELETE {policy_id} completes without raising."""
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin"),
        patch(f"{_ROUTER}.delete_policy", return_value=None),
    ):
        from app.api.v1.corporate_travel_policies import delete_travel_policy

        await delete_travel_policy(
            policy_id=POLICY_ID, user=MagicMock(id=ADMIN_ID), db=AsyncMock()
        )


@pytest.mark.asyncio
async def test_api_delete_travel_policy_409_when_active():
    """DELETE {policy_id} raises 409 when policy is active."""
    from fastapi import HTTPException

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin"),
        patch(
            f"{_ROUTER}.delete_policy",
            side_effect=HTTPException(
                status_code=409, detail="Cannot delete active policy"
            ),
        ),
    ):
        from app.api.v1.corporate_travel_policies import delete_travel_policy

        with pytest.raises(HTTPException) as exc:
            await delete_travel_policy(
                policy_id=POLICY_ID, user=MagicMock(id=ADMIN_ID), db=AsyncMock()
            )
    assert exc.value.status_code == 409


# --- GET acknowledgements ---


@pytest.mark.asyncio
async def test_api_get_policy_acknowledgements_200():
    """GET acknowledgements returns summary with ack list."""
    ack_resp = AcknowledgementResponse(
        id=ACK_ID,
        policy_id=POLICY_ID,
        member_id=MEMBER_ID,
        account_id=ACCOUNT_ID,
        acknowledged_at=NOW,
    )
    summary = AcknowledgementSummary(
        policy_id=POLICY_ID,
        total_acknowledged=1,
        acknowledgements=[ack_resp],
    )
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin"),
        patch(f"{_ROUTER}.get_acknowledgement_summary", return_value=summary),
    ):
        from app.api.v1.corporate_travel_policies import get_policy_acknowledgements

        result = await get_policy_acknowledgements(
            policy_id=POLICY_ID, user=MagicMock(id=ADMIN_ID), db=AsyncMock()
        )
    assert result.total_acknowledged == 1


@pytest.mark.asyncio
async def test_api_get_policy_acknowledgements_403_non_admin():
    """GET acknowledgements raises 403 for non-admin."""
    from fastapi import HTTPException

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(
            f"{_ROUTER}._require_account_admin",
            side_effect=HTTPException(status_code=403, detail="Forbidden"),
        ),
    ):
        from app.api.v1.corporate_travel_policies import get_policy_acknowledgements

        with pytest.raises(HTTPException) as exc:
            await get_policy_acknowledgements(
                policy_id=POLICY_ID, user=MagicMock(id=MEMBER_ID), db=AsyncMock()
            )
    assert exc.value.status_code == 403


# --- Platform-admin ---


@pytest.mark.asyncio
async def test_api_platform_list_all_travel_policies_200():
    """Platform-admin list-all returns all policies."""
    policies_resp = TravelPolicyListResponse(items=[], total=0)

    with patch(f"{_ROUTER}.list_all_platform", return_value=policies_resp):
        from app.api.v1.corporate_travel_policies import admin_list_all_travel_policies

        result = await admin_list_all_travel_policies(
            account_id=None, _admin=MagicMock(), db=AsyncMock()
        )
    assert result.total == 0


@pytest.mark.asyncio
async def test_api_platform_list_account_travel_policies_200():
    """Platform-admin list-for-account returns policies for a specific account."""
    policies_resp = TravelPolicyListResponse(items=[], total=0)

    with patch(f"{_ROUTER}.list_policies", return_value=policies_resp):
        from app.api.v1.corporate_travel_policies import admin_list_account_travel_policies

        result = await admin_list_account_travel_policies(
            account_id=ACCOUNT_ID, is_active=None, _admin=MagicMock(), db=AsyncMock()
        )
    assert result.total == 0
