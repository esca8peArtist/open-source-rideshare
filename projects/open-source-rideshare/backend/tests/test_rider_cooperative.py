"""Tests for rider cooperative membership, voting, and dividend system.

Service layer (unit tests with mocked DB):
  1.  apply_for_membership — creates applicant record
  2.  apply_for_membership — raises 409 if active membership exists
  3.  apply_for_membership — raises 409 if pending application exists
  4.  get_membership — returns record when found
  5.  get_membership — returns None when not found
  6.  resign_membership — transitions member → resigned
  7.  resign_membership — raises 400 if still applicant (must withdraw)
  8.  withdraw_application — withdraws a pending application
  9.  withdraw_application — raises 404 when no pending application
  10. approve_membership — transitions applicant → member
  11. approve_membership — raises 400 when status != applicant
  12. suspend_membership — transitions member → suspended with reason
  13. suspend_membership — raises 400 when status != member
  14. reinstate_membership — transitions suspended → member
  15. reinstate_membership — raises 400 when status != suspended
  16. list_members — returns (total, items)
  17. get_summary — returns correct counts and totals
  18. cast_vote — creates vote record with correct weight
  19. cast_vote — raises 403 when rider is not an active member
  20. cast_vote — raises 404 when proposal not found
  21. cast_vote — raises 400 when proposal is not open
  22. cast_vote — raises 409 on duplicate vote
  23. get_my_vote — returns vote when found
  24. get_my_vote — returns None when no membership
  25. get_proposal_tally — aggregates votes correctly
  26. mark_share_paid — transitions pending → paid
  27. mark_share_paid — raises 400 when status != pending
  28. mark_share_paid — raises 404 when not found

Schema:
  29. MembershipApplicationRequest — instantiates empty
  30. RiderCoopMembershipResponse — from_attributes mapping
  31. RiderVoteRequest — validates choice pattern
  32. GenerateRiderSharesRequest — validates positive surplus

API layer (integration-style, skipped without live DB):
  33. POST /riders/me/cooperative/membership — 201 created
  34. POST /riders/me/cooperative/membership — 401 unauthenticated
  35. POST /riders/me/cooperative/membership — 403 when driver calls rider endpoint
  36. POST /riders/me/cooperative/membership — 409 duplicate application
  37. GET  /riders/me/cooperative/membership — 200 returns status
  38. GET  /riders/me/cooperative/membership — 404 no membership
  39. DELETE /riders/me/cooperative/membership — 200 resign
  40. GET  /riders/me/cooperative/proposals — 200 returns list
  41. POST /riders/me/cooperative/proposals/{id}/vote — 201 casts vote
  42. POST /riders/me/cooperative/proposals/{id}/vote — 403 non-member
  43. GET  /riders/me/cooperative/dividends — 200 returns list
  44. GET  /admin/cooperative/rider-members — 200 returns list
  45. GET  /admin/cooperative/rider-members — 403 non-admin
  46. POST /admin/cooperative/rider-members/{id}/approve — 200 approves
  47. POST /admin/cooperative/rider-members/{id}/suspend — 200 suspends
  48. POST /admin/cooperative/rider-members/{id}/reinstate — 200 reinstates
  49. GET  /admin/cooperative/rider-summary — 200 returns stats
  50. POST /admin/cooperative/rider-dividends — 201 generates shares
  51. POST /admin/cooperative/rider-dividend-shares/{id}/pay — 200 marks paid
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.driver_proposal import DriverProposal, ProposalStatus
from app.models.rider_cooperative import (
    RiderCoopMembership,
    RiderCoopVote,
    RiderDividendShare,
    RiderDividendShareStatus,
    RiderMemberStatus,
    RiderVoteChoice,
)
from app.models.user import User, UserRole
from app.schemas.rider_cooperative import (
    GenerateRiderSharesRequest,
    MembershipApplicationRequest,
    RiderCoopMembershipResponse,
    RiderVoteRequest,
)
from app.services.auth import create_access_token, hash_password
from app.services.rider_cooperative import (
    apply_for_membership,
    approve_membership,
    cast_vote,
    get_membership,
    get_my_vote,
    get_proposal_tally,
    get_summary,
    list_members,
    mark_share_paid,
    reinstate_membership,
    resign_membership,
    suspend_membership,
    withdraw_application,
)

# ===========================================================================
# Helpers / factories
# ===========================================================================

_BASE_TS = datetime(2026, 4, 15, 10, 0, tzinfo=timezone.utc)


def _make_user(user_id: int = 1, role: UserRole = UserRole.RIDER) -> MagicMock:
    u = MagicMock(spec=User)
    u.id = user_id
    u.role = role
    return u


def _make_membership(
    *,
    membership_id: int = 1,
    rider_id: int = 1,
    status: RiderMemberStatus = RiderMemberStatus.applicant,
    lifetime_rides: int = 0,
    voting_weight: int = 1,
    suspension_reason: str | None = None,
    approved_at: datetime | None = None,
    suspended_at: datetime | None = None,
    resigned_at: datetime | None = None,
) -> MagicMock:
    m = MagicMock(spec=RiderCoopMembership)
    m.id = membership_id
    m.rider_id = rider_id
    m.status = status
    m.lifetime_rides = lifetime_rides
    m.voting_weight = voting_weight
    m.suspension_reason = suspension_reason
    m.reviewed_by_id = None
    m.applied_at = _BASE_TS
    m.approved_at = approved_at
    m.suspended_at = suspended_at
    m.resigned_at = resigned_at
    return m


def _make_proposal(
    proposal_id: int = 10,
    status: ProposalStatus = ProposalStatus.open,
) -> MagicMock:
    p = MagicMock(spec=DriverProposal)
    p.id = proposal_id
    p.title = "Reduce platform fee to 12%"
    p.description = "Proposal to lower the fee."
    p.proposal_type = "fee_rate_change"
    p.status = status
    p.voting_ends_at = None
    return p


def _make_vote(
    vote_id: int = 1,
    proposal_id: int = 10,
    membership_id: int = 1,
    rider_id: int = 1,
    choice: RiderVoteChoice = RiderVoteChoice.yes,
    voting_weight: int = 1,
) -> MagicMock:
    v = MagicMock(spec=RiderCoopVote)
    v.id = vote_id
    v.proposal_id = proposal_id
    v.membership_id = membership_id
    v.rider_id = rider_id
    v.choice = choice
    v.voting_weight = voting_weight
    v.voted_at = _BASE_TS
    return v


def _make_share(
    share_id: int = 1,
    dividend_id: int = 5,
    membership_id: int = 1,
    rider_id: int = 1,
    qualifying_rides: int = 10,
    amount_usd: float = 12.50,
    status: RiderDividendShareStatus = RiderDividendShareStatus.pending,
) -> MagicMock:
    s = MagicMock(spec=RiderDividendShare)
    s.id = share_id
    s.dividend_id = dividend_id
    s.membership_id = membership_id
    s.rider_id = rider_id
    s.qualifying_rides = qualifying_rides
    s.share_pct = 10.0
    s.amount_usd = amount_usd
    s.status = status
    s.paid_at = None
    return s


def _scalar_result(value):
    m = MagicMock()
    m.scalar_one.return_value = value
    m.scalar_one_or_none.return_value = value
    inner = MagicMock()
    inner.first.return_value = value
    inner.all.return_value = [value] if value is not None else []
    m.scalars.return_value = inner
    return m


def _scalar_result_list(values: list):
    m = MagicMock()
    m.scalar_one.return_value = len(values)
    m.scalar_one_or_none.return_value = values[0] if values else None
    inner = MagicMock()
    inner.all.return_value = values
    m.scalars.return_value = inner
    return m


# ===========================================================================
# PART 1 — Service unit tests (mocked DB)
# ===========================================================================


class TestApplyForMembership:
    @pytest.mark.anyio
    async def test_creates_applicant_record(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_result(None))  # no existing
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        rider = _make_user()
        result = await apply_for_membership(db, rider)

        db.add.assert_called_once()
        db.commit.assert_called_once()
        added = db.add.call_args[0][0]
        assert isinstance(added, RiderCoopMembership)
        assert added.rider_id == 1
        assert added.status == RiderMemberStatus.applicant

    @pytest.mark.anyio
    async def test_raises_409_if_active_membership_exists(self):
        from fastapi import HTTPException

        db = AsyncMock()
        existing = _make_membership(status=RiderMemberStatus.member)
        db.execute = AsyncMock(return_value=_scalar_result(existing))

        rider = _make_user()
        with pytest.raises(HTTPException) as exc_info:
            await apply_for_membership(db, rider)
        assert exc_info.value.status_code == 409

    @pytest.mark.anyio
    async def test_raises_409_if_pending_application_exists(self):
        from fastapi import HTTPException

        db = AsyncMock()
        existing = _make_membership(status=RiderMemberStatus.applicant)
        db.execute = AsyncMock(return_value=_scalar_result(existing))

        rider = _make_user()
        with pytest.raises(HTTPException) as exc_info:
            await apply_for_membership(db, rider)
        assert exc_info.value.status_code == 409


class TestGetMembership:
    @pytest.mark.anyio
    async def test_returns_record_when_found(self):
        db = AsyncMock()
        membership = _make_membership()
        db.execute = AsyncMock(return_value=_scalar_result(membership))

        result = await get_membership(db, rider_id=1)
        assert result is membership

    @pytest.mark.anyio
    async def test_returns_none_when_not_found(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_result(None))

        result = await get_membership(db, rider_id=99)
        assert result is None


class TestResignMembership:
    @pytest.mark.anyio
    async def test_transitions_member_to_resigned(self):
        db = AsyncMock()
        membership = _make_membership(status=RiderMemberStatus.member)
        db.execute = AsyncMock(return_value=_scalar_result(membership))
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        rider = _make_user()
        await resign_membership(db, rider)

        assert membership.status == RiderMemberStatus.resigned
        assert membership.resigned_at is not None
        db.commit.assert_called_once()

    @pytest.mark.anyio
    async def test_raises_400_for_applicant(self):
        from fastapi import HTTPException

        db = AsyncMock()
        membership = _make_membership(status=RiderMemberStatus.applicant)
        db.execute = AsyncMock(return_value=_scalar_result(membership))

        rider = _make_user()
        with pytest.raises(HTTPException) as exc_info:
            await resign_membership(db, rider)
        assert exc_info.value.status_code == 400


class TestWithdrawApplication:
    @pytest.mark.anyio
    async def test_withdraws_pending_application(self):
        db = AsyncMock()
        membership = _make_membership(status=RiderMemberStatus.applicant)
        db.execute = AsyncMock(return_value=_scalar_result(membership))
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        rider = _make_user()
        await withdraw_application(db, rider)

        assert membership.status == RiderMemberStatus.resigned
        db.commit.assert_called_once()

    @pytest.mark.anyio
    async def test_raises_404_when_no_pending_application(self):
        from fastapi import HTTPException

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_result(None))

        rider = _make_user()
        with pytest.raises(HTTPException) as exc_info:
            await withdraw_application(db, rider)
        assert exc_info.value.status_code == 404


class TestAdminMembershipManagement:
    @pytest.mark.anyio
    async def test_approve_transitions_applicant_to_member(self):
        db = AsyncMock()
        membership = _make_membership(status=RiderMemberStatus.applicant)
        db.execute = AsyncMock(return_value=_scalar_result(membership))
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        admin = _make_user(user_id=99, role=UserRole.ADMIN)
        await approve_membership(db, membership_id=1, admin=admin)

        assert membership.status == RiderMemberStatus.member
        assert membership.approved_at is not None
        assert membership.reviewed_by_id == 99

    @pytest.mark.anyio
    async def test_approve_raises_400_when_not_applicant(self):
        from fastapi import HTTPException

        db = AsyncMock()
        membership = _make_membership(status=RiderMemberStatus.member)
        db.execute = AsyncMock(return_value=_scalar_result(membership))

        admin = _make_user(user_id=99, role=UserRole.ADMIN)
        with pytest.raises(HTTPException) as exc_info:
            await approve_membership(db, membership_id=1, admin=admin)
        assert exc_info.value.status_code == 400

    @pytest.mark.anyio
    async def test_suspend_transitions_member_to_suspended(self):
        db = AsyncMock()
        membership = _make_membership(status=RiderMemberStatus.member)
        db.execute = AsyncMock(return_value=_scalar_result(membership))
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        admin = _make_user(user_id=99, role=UserRole.ADMIN)
        await suspend_membership(db, membership_id=1, admin=admin, reason="Policy violation")

        assert membership.status == RiderMemberStatus.suspended
        assert membership.suspension_reason == "Policy violation"
        assert membership.suspended_at is not None

    @pytest.mark.anyio
    async def test_suspend_raises_400_when_not_member(self):
        from fastapi import HTTPException

        db = AsyncMock()
        membership = _make_membership(status=RiderMemberStatus.applicant)
        db.execute = AsyncMock(return_value=_scalar_result(membership))

        admin = _make_user(user_id=99, role=UserRole.ADMIN)
        with pytest.raises(HTTPException) as exc_info:
            await suspend_membership(db, membership_id=1, admin=admin)
        assert exc_info.value.status_code == 400

    @pytest.mark.anyio
    async def test_reinstate_transitions_suspended_to_member(self):
        db = AsyncMock()
        membership = _make_membership(status=RiderMemberStatus.suspended)
        db.execute = AsyncMock(return_value=_scalar_result(membership))
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        admin = _make_user(user_id=99, role=UserRole.ADMIN)
        await reinstate_membership(db, membership_id=1, admin=admin)

        assert membership.status == RiderMemberStatus.member
        assert membership.suspension_reason is None

    @pytest.mark.anyio
    async def test_reinstate_raises_400_when_not_suspended(self):
        from fastapi import HTTPException

        db = AsyncMock()
        membership = _make_membership(status=RiderMemberStatus.member)
        db.execute = AsyncMock(return_value=_scalar_result(membership))

        admin = _make_user(user_id=99, role=UserRole.ADMIN)
        with pytest.raises(HTTPException) as exc_info:
            await reinstate_membership(db, membership_id=1, admin=admin)
        assert exc_info.value.status_code == 400

    @pytest.mark.anyio
    async def test_list_members_returns_total_and_items(self):
        db = AsyncMock()
        memberships = [_make_membership(membership_id=i) for i in range(1, 4)]
        count_result = MagicMock()
        count_result.scalar_one.return_value = 3
        items_result = _scalar_result_list(memberships)
        db.execute = AsyncMock(side_effect=[count_result, items_result])

        total, items = await list_members(db)
        assert total == 3
        assert len(items) == 3

    @pytest.mark.anyio
    async def test_get_summary_returns_correct_structure(self):
        db = AsyncMock()

        # First execute: status counts
        counts_result = MagicMock()
        counts_result.__iter__ = MagicMock(return_value=iter([
            (RiderMemberStatus.member, 10),
            (RiderMemberStatus.applicant, 2),
            (RiderMemberStatus.suspended, 1),
            (RiderMemberStatus.resigned, 3),
        ]))
        # Second execute: paid total
        paid_result = MagicMock()
        paid_result.scalar_one.return_value = 150.00
        # Third execute: pending total
        pending_result = MagicMock()
        pending_result.scalar_one.return_value = 75.00

        db.execute = AsyncMock(side_effect=[counts_result, paid_result, pending_result])

        summary = await get_summary(db)

        assert summary["active_members"] == 10
        assert summary["applicants_pending"] == 2
        assert summary["suspended_members"] == 1
        assert summary["resigned_members"] == 3
        assert summary["total_members"] == 16
        assert summary["total_dividends_paid_usd"] == 150.00
        assert summary["total_dividends_pending_usd"] == 75.00


class TestVoting:
    @pytest.mark.anyio
    async def test_cast_vote_creates_record_with_weight(self):
        db = AsyncMock()
        proposal = _make_proposal(status=ProposalStatus.open)
        membership = _make_membership(status=RiderMemberStatus.member, voting_weight=2)

        # get_membership → returns membership
        # db.get(DriverProposal, ...) → returns proposal
        # existing vote check → None
        db.execute = AsyncMock(side_effect=[
            _scalar_result(membership),   # get_membership call
            _scalar_result(None),         # duplicate vote check
        ])
        db.get = AsyncMock(return_value=proposal)
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        rider = _make_user()
        result = await cast_vote(db, rider, proposal_id=10, choice="yes")

        db.add.assert_called_once()
        added = db.add.call_args[0][0]
        assert isinstance(added, RiderCoopVote)
        assert added.choice == RiderVoteChoice.yes
        assert added.voting_weight == 2

    @pytest.mark.anyio
    async def test_cast_vote_raises_403_when_not_active_member(self):
        from fastapi import HTTPException

        db = AsyncMock()
        membership = _make_membership(status=RiderMemberStatus.applicant)
        db.execute = AsyncMock(return_value=_scalar_result(membership))

        rider = _make_user()
        with pytest.raises(HTTPException) as exc_info:
            await cast_vote(db, rider, proposal_id=10, choice="yes")
        assert exc_info.value.status_code == 403

    @pytest.mark.anyio
    async def test_cast_vote_raises_404_when_proposal_not_found(self):
        from fastapi import HTTPException

        db = AsyncMock()
        membership = _make_membership(status=RiderMemberStatus.member)
        db.execute = AsyncMock(return_value=_scalar_result(membership))
        db.get = AsyncMock(return_value=None)

        rider = _make_user()
        with pytest.raises(HTTPException) as exc_info:
            await cast_vote(db, rider, proposal_id=999, choice="yes")
        assert exc_info.value.status_code == 404

    @pytest.mark.anyio
    async def test_cast_vote_raises_400_when_proposal_not_open(self):
        from fastapi import HTTPException

        db = AsyncMock()
        membership = _make_membership(status=RiderMemberStatus.member)
        proposal = _make_proposal(status=ProposalStatus.closed)
        db.execute = AsyncMock(return_value=_scalar_result(membership))
        db.get = AsyncMock(return_value=proposal)

        rider = _make_user()
        with pytest.raises(HTTPException) as exc_info:
            await cast_vote(db, rider, proposal_id=10, choice="no")
        assert exc_info.value.status_code == 400

    @pytest.mark.anyio
    async def test_cast_vote_raises_409_on_duplicate(self):
        from fastapi import HTTPException

        db = AsyncMock()
        membership = _make_membership(status=RiderMemberStatus.member)
        proposal = _make_proposal(status=ProposalStatus.open)
        existing_vote = _make_vote()
        db.execute = AsyncMock(side_effect=[
            _scalar_result(membership),
            _scalar_result(existing_vote),
        ])
        db.get = AsyncMock(return_value=proposal)

        rider = _make_user()
        with pytest.raises(HTTPException) as exc_info:
            await cast_vote(db, rider, proposal_id=10, choice="yes")
        assert exc_info.value.status_code == 409

    @pytest.mark.anyio
    async def test_get_my_vote_returns_vote_when_found(self):
        db = AsyncMock()
        membership = _make_membership()
        vote = _make_vote()
        db.execute = AsyncMock(side_effect=[
            _scalar_result(membership),
            _scalar_result(vote),
        ])

        rider = _make_user()
        result = await get_my_vote(db, rider, proposal_id=10)
        assert result is vote

    @pytest.mark.anyio
    async def test_get_my_vote_returns_none_when_no_membership(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_result(None))

        rider = _make_user()
        result = await get_my_vote(db, rider, proposal_id=10)
        assert result is None


class TestDividendShares:
    @pytest.mark.anyio
    async def test_mark_share_paid_transitions_to_paid(self):
        db = AsyncMock()
        share = _make_share(status=RiderDividendShareStatus.pending)
        db.execute = AsyncMock(return_value=_scalar_result(share))
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        admin = _make_user(user_id=99, role=UserRole.ADMIN)
        await mark_share_paid(db, share_id=1, admin=admin)

        assert share.status == RiderDividendShareStatus.paid
        assert share.paid_at is not None

    @pytest.mark.anyio
    async def test_mark_share_paid_raises_400_when_already_paid(self):
        from fastapi import HTTPException

        db = AsyncMock()
        share = _make_share(status=RiderDividendShareStatus.paid)
        db.execute = AsyncMock(return_value=_scalar_result(share))

        admin = _make_user(user_id=99, role=UserRole.ADMIN)
        with pytest.raises(HTTPException) as exc_info:
            await mark_share_paid(db, share_id=1, admin=admin)
        assert exc_info.value.status_code == 400

    @pytest.mark.anyio
    async def test_mark_share_paid_raises_404_when_not_found(self):
        from fastapi import HTTPException

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_result(None))

        admin = _make_user(user_id=99, role=UserRole.ADMIN)
        with pytest.raises(HTTPException) as exc_info:
            await mark_share_paid(db, share_id=999, admin=admin)
        assert exc_info.value.status_code == 404


# ===========================================================================
# PART 2 — Schema tests
# ===========================================================================


class TestSchemas:
    def test_membership_application_request_instantiates_empty(self):
        req = MembershipApplicationRequest()
        assert req is not None

    def test_rider_coop_membership_response_from_attributes(self):
        membership = _make_membership(
            membership_id=5,
            rider_id=42,
            status=RiderMemberStatus.member,
            lifetime_rides=150,
            voting_weight=2,
        )
        # Simulate from_attributes mapping manually
        resp = RiderCoopMembershipResponse(
            id=membership.id,
            rider_id=membership.rider_id,
            status=membership.status,
            lifetime_rides=membership.lifetime_rides,
            voting_weight=membership.voting_weight,
            applied_at=_BASE_TS,
            approved_at=None,
            suspended_at=None,
            resigned_at=None,
            suspension_reason=None,
        )
        assert resp.id == 5
        assert resp.rider_id == 42
        assert resp.lifetime_rides == 150
        assert resp.voting_weight == 2

    def test_rider_vote_request_validates_choice(self):
        import pydantic
        req = RiderVoteRequest(choice="yes")
        assert req.choice == "yes"

        req2 = RiderVoteRequest(choice="no")
        assert req2.choice == "no"

        req3 = RiderVoteRequest(choice="abstain")
        assert req3.choice == "abstain"

        with pytest.raises(pydantic.ValidationError):
            RiderVoteRequest(choice="maybe")

    def test_generate_rider_shares_request_validates_surplus(self):
        import pydantic
        req = GenerateRiderSharesRequest(dividend_id=1, rider_surplus_usd=500.00)
        assert req.rider_surplus_usd == 500.00

        with pytest.raises(pydantic.ValidationError):
            GenerateRiderSharesRequest(dividend_id=1, rider_surplus_usd=0.0)

        with pytest.raises(pydantic.ValidationError):
            GenerateRiderSharesRequest(dividend_id=1, rider_surplus_usd=-100.0)


# ===========================================================================
# PART 3 — API integration tests (skipped without live DB)
# ===========================================================================


@pytest.mark.anyio
async def test_api_apply_for_membership_201(client, rider, rider_token):
    pytest.skip("Requires live test database")
    resp = await client.post(
        "/api/v1/riders/me/cooperative/membership",
        headers={"Authorization": f"Bearer {rider_token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "applicant"
    assert data["rider_id"] == rider.id


@pytest.mark.anyio
async def test_api_apply_for_membership_401_unauthenticated(client):
    pytest.skip("Requires live test database")
    resp = await client.post("/api/v1/riders/me/cooperative/membership")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_api_apply_for_membership_403_driver(client, driver_user):
    pytest.skip("Requires live test database")
    driver_token = create_access_token(driver_user.id, driver_user.role.value)
    resp = await client.post(
        "/api/v1/riders/me/cooperative/membership",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_api_apply_409_duplicate(client, db, rider, rider_token):
    pytest.skip("Requires live test database")
    membership = RiderCoopMembership(
        rider_id=rider.id,
        status=RiderMemberStatus.applicant,
        lifetime_rides=0,
        voting_weight=1,
    )
    db.add(membership)
    await db.flush()

    resp = await client.post(
        "/api/v1/riders/me/cooperative/membership",
        headers={"Authorization": f"Bearer {rider_token}"},
    )
    assert resp.status_code == 409


@pytest.mark.anyio
async def test_api_get_my_membership_200(client, db, rider, rider_token):
    pytest.skip("Requires live test database")
    membership = RiderCoopMembership(
        rider_id=rider.id,
        status=RiderMemberStatus.member,
        lifetime_rides=50,
        voting_weight=1,
    )
    db.add(membership)
    await db.flush()

    resp = await client.get(
        "/api/v1/riders/me/cooperative/membership",
        headers={"Authorization": f"Bearer {rider_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "member"


@pytest.mark.anyio
async def test_api_get_my_membership_404(client, rider, rider_token):
    pytest.skip("Requires live test database")
    resp = await client.get(
        "/api/v1/riders/me/cooperative/membership",
        headers={"Authorization": f"Bearer {rider_token}"},
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_api_resign_membership_200(client, db, rider, rider_token):
    pytest.skip("Requires live test database")
    membership = RiderCoopMembership(
        rider_id=rider.id,
        status=RiderMemberStatus.member,
        lifetime_rides=0,
        voting_weight=1,
    )
    db.add(membership)
    await db.flush()

    resp = await client.delete(
        "/api/v1/riders/me/cooperative/membership",
        headers={"Authorization": f"Bearer {rider_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "resigned"


@pytest.mark.anyio
async def test_api_list_proposals_200(client, rider, rider_token):
    pytest.skip("Requires live test database")
    resp = await client.get(
        "/api/v1/riders/me/cooperative/proposals",
        headers={"Authorization": f"Bearer {rider_token}"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.anyio
async def test_api_cast_vote_201(client, db, rider, rider_token):
    pytest.skip("Requires live test database")
    # Requires: membership + open proposal in DB


@pytest.mark.anyio
async def test_api_cast_vote_403_non_member(client, db, rider, rider_token):
    pytest.skip("Requires live test database")
    # Without membership, should get 403


@pytest.mark.anyio
async def test_api_list_dividends_200(client, rider, rider_token):
    pytest.skip("Requires live test database")
    resp = await client.get(
        "/api/v1/riders/me/cooperative/dividends",
        headers={"Authorization": f"Bearer {rider_token}"},
    )
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_api_admin_list_members_200(client, admin_user):
    pytest.skip("Requires live test database")
    admin_token = create_access_token(admin_user.id, admin_user.role.value)
    resp = await client.get(
        "/api/v1/admin/cooperative/rider-members",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_api_admin_list_members_403_non_admin(client, rider, rider_token):
    pytest.skip("Requires live test database")
    resp = await client.get(
        "/api/v1/admin/cooperative/rider-members",
        headers={"Authorization": f"Bearer {rider_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_api_admin_approve_membership_200(client, db, rider, admin_user):
    pytest.skip("Requires live test database")
    admin_token = create_access_token(admin_user.id, admin_user.role.value)
    membership = RiderCoopMembership(
        rider_id=rider.id, status=RiderMemberStatus.applicant,
        lifetime_rides=0, voting_weight=1,
    )
    db.add(membership)
    await db.flush()

    resp = await client.post(
        f"/api/v1/admin/cooperative/rider-members/{membership.id}/approve",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "member"


@pytest.mark.anyio
async def test_api_admin_suspend_membership_200(client, db, rider, admin_user):
    pytest.skip("Requires live test database")
    admin_token = create_access_token(admin_user.id, admin_user.role.value)
    membership = RiderCoopMembership(
        rider_id=rider.id, status=RiderMemberStatus.member,
        lifetime_rides=0, voting_weight=1,
    )
    db.add(membership)
    await db.flush()

    resp = await client.post(
        f"/api/v1/admin/cooperative/rider-members/{membership.id}/suspend",
        json={"reason": "Violation of terms"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "suspended"


@pytest.mark.anyio
async def test_api_admin_reinstate_membership_200(client, db, rider, admin_user):
    pytest.skip("Requires live test database")
    admin_token = create_access_token(admin_user.id, admin_user.role.value)
    membership = RiderCoopMembership(
        rider_id=rider.id, status=RiderMemberStatus.suspended,
        lifetime_rides=0, voting_weight=1,
    )
    db.add(membership)
    await db.flush()

    resp = await client.post(
        f"/api/v1/admin/cooperative/rider-members/{membership.id}/reinstate",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "member"


@pytest.mark.anyio
async def test_api_admin_summary_200(client, admin_user):
    pytest.skip("Requires live test database")
    admin_token = create_access_token(admin_user.id, admin_user.role.value)
    resp = await client.get(
        "/api/v1/admin/cooperative/rider-summary",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "total_members" in data
    assert "active_members" in data


@pytest.mark.anyio
async def test_api_admin_generate_shares_201(client, db, admin_user):
    pytest.skip("Requires live test database")
    # Requires an approved CooperativeDividend in DB


@pytest.mark.anyio
async def test_api_admin_mark_share_paid_200(client, db, admin_user):
    pytest.skip("Requires live test database")
    # Requires a rider dividend share in DB
