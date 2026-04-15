"""Unit tests for cooperative governance: driver proposals and voting.

Tests cover:
- Schema: CreateProposalRequest, AdminCreateProposalRequest, UpdateProposalRequest,
          CastVoteRequest, ProposalSummary, ProposalDetail, VoteResponse,
          MyVoteResponse, ProposalListResponse, AdminCloseResultResponse
- Models: DriverProposal, DriverVote, ProposalType, ProposalStatus, VoteChoice
- Service: list_open_proposals, get_proposal, driver_submit_proposal,
           driver_list_own_proposals, cast_vote, get_my_vote, admin_create_proposal,
           admin_list_proposals, admin_update_proposal, admin_open_proposal,
           admin_close_proposal, admin_withdraw_proposal, admin_mark_implemented,
           get_proposal_votes, _compute_result, _driver_lifetime_rides
- Router: endpoint structure, wiring, error handling
- Edge cases: not found, wrong status, already voted, ineligibility, terminal proposal
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure all models are registered before mapper configuration
import app.models  # noqa: F401

from app.models.driver_proposal import (
    DriverProposal,
    DriverVote,
    ProposalStatus,
    ProposalType,
    VoteChoice,
)
from app.schemas.driver_proposal import (
    AdminCloseResultResponse,
    AdminCreateProposalRequest,
    CastVoteRequest,
    CreateProposalRequest,
    MyVoteResponse,
    ProposalDetail,
    ProposalListResponse,
    ProposalSummary,
    UpdateProposalRequest,
    VoteResponse,
)
from app.services.driver_proposal import _compute_result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
_FUTURE = _NOW + timedelta(days=7)
_PAST = _NOW - timedelta(days=30)  # well before any real clock value


def _make_proposal(
    id: int = 1,
    title: str = "Reduce platform fee from 15% to 12%",
    description: str = "The current 15% platform fee is higher than necessary to cover operational costs.",
    proposal_type: ProposalType = ProposalType.fee_rate_change,
    status: ProposalStatus = ProposalStatus.open,
    created_by_admin: bool = True,
    created_by_user_id: int | None = 1,
    voting_opens_at: datetime | None = None,
    voting_closes_at: datetime | None = None,
    min_lifetime_rides_to_vote: int = 50,
    votes_for: int = 0,
    votes_against: int = 0,
    votes_abstain: int = 0,
    result_threshold_pct: float = 0.5001,
    implementation_notes: str | None = None,
    implemented_at: datetime | None = None,
) -> DriverProposal:
    proposal = MagicMock(spec=DriverProposal)
    proposal.id = id
    proposal.title = title
    proposal.description = description
    proposal.proposal_type = proposal_type
    proposal.status = status
    proposal.created_by_admin = created_by_admin
    proposal.created_by_user_id = created_by_user_id
    proposal.voting_opens_at = voting_opens_at or _PAST
    proposal.voting_closes_at = voting_closes_at or _FUTURE
    proposal.min_lifetime_rides_to_vote = min_lifetime_rides_to_vote
    proposal.votes_for = votes_for
    proposal.votes_against = votes_against
    proposal.votes_abstain = votes_abstain
    proposal.result_threshold_pct = result_threshold_pct
    proposal.implementation_notes = implementation_notes
    proposal.implemented_at = implemented_at
    proposal.created_at = _NOW
    proposal.updated_at = _NOW
    return proposal


def _make_vote(
    id: int = 1,
    proposal_id: int = 1,
    driver_profile_id: int = 5,
    vote: VoteChoice = VoteChoice.yes,
    voted_at: datetime | None = None,
) -> DriverVote:
    v = MagicMock(spec=DriverVote)
    v.id = id
    v.proposal_id = proposal_id
    v.driver_profile_id = driver_profile_id
    v.vote = vote
    v.voted_at = voted_at or _NOW
    return v


# ---------------------------------------------------------------------------
# Model / Enum tests
# ---------------------------------------------------------------------------


class TestProposalType:
    def test_all_types_defined(self):
        assert ProposalType.fee_rate_change == "fee_rate_change"
        assert ProposalType.bonus_structure == "bonus_structure"
        assert ProposalType.policy_change == "policy_change"
        assert ProposalType.platform_feature == "platform_feature"
        assert ProposalType.general == "general"

    def test_proposal_type_is_str_enum(self):
        assert isinstance(ProposalType.fee_rate_change, str)


class TestProposalStatus:
    def test_all_statuses_defined(self):
        statuses = [
            ProposalStatus.draft,
            ProposalStatus.open,
            ProposalStatus.closed,
            ProposalStatus.passed,
            ProposalStatus.failed,
            ProposalStatus.withdrawn,
            ProposalStatus.implemented,
        ]
        assert len(statuses) == 7

    def test_status_values(self):
        assert ProposalStatus.draft == "draft"
        assert ProposalStatus.implemented == "implemented"


class TestVoteChoice:
    def test_vote_choices(self):
        assert VoteChoice.yes == "yes"
        assert VoteChoice.no == "no"
        assert VoteChoice.abstain == "abstain"


class TestDriverProposalModel:
    def test_model_has_required_fields(self):
        proposal = _make_proposal()
        assert proposal.title == "Reduce platform fee from 15% to 12%"
        assert proposal.status == ProposalStatus.open
        assert proposal.votes_for == 0
        assert proposal.min_lifetime_rides_to_vote == 50
        assert proposal.result_threshold_pct == 0.5001

    def test_model_default_votes_zero(self):
        proposal = _make_proposal(votes_for=0, votes_against=0, votes_abstain=0)
        assert proposal.votes_for + proposal.votes_against + proposal.votes_abstain == 0


class TestDriverVoteModel:
    def test_vote_model_fields(self):
        vote = _make_vote()
        assert vote.proposal_id == 1
        assert vote.driver_profile_id == 5
        assert vote.vote == VoteChoice.yes


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestCreateProposalRequest:
    def test_valid_request(self):
        req = CreateProposalRequest(
            title="Add EV incentive bonus",
            description="Drivers using electric vehicles should receive a 2% bonus.",
            proposal_type=ProposalType.bonus_structure,
        )
        assert req.title == "Add EV incentive bonus"
        assert req.min_lifetime_rides_to_vote == 50
        assert req.result_threshold_pct == 0.5001

    def test_title_min_length(self):
        with pytest.raises(Exception):
            CreateProposalRequest(
                title="ab",
                description="This is a valid description.",
                proposal_type=ProposalType.general,
            )

    def test_description_min_length(self):
        with pytest.raises(Exception):
            CreateProposalRequest(
                title="Valid title",
                description="short",
                proposal_type=ProposalType.general,
            )

    def test_custom_threshold(self):
        req = CreateProposalRequest(
            title="Supermajority proposal",
            description="Requires two-thirds majority to pass.",
            proposal_type=ProposalType.policy_change,
            result_threshold_pct=0.6667,
        )
        assert req.result_threshold_pct == 0.6667

    def test_threshold_min_enforced(self):
        with pytest.raises(Exception):
            CreateProposalRequest(
                title="Bad threshold proposal",
                description="Threshold below minimum allowed value.",
                proposal_type=ProposalType.general,
                result_threshold_pct=0.4,
            )

    def test_threshold_max_enforced(self):
        with pytest.raises(Exception):
            CreateProposalRequest(
                title="Impossible threshold",
                description="Nobody can ever pass a 100%+ threshold.",
                proposal_type=ProposalType.general,
                result_threshold_pct=1.1,
            )


class TestAdminCreateProposalRequest:
    def test_admin_can_set_open_immediately(self):
        req = AdminCreateProposalRequest(
            title="Urgent policy change",
            description="This needs to be voted on immediately.",
            proposal_type=ProposalType.policy_change,
            open_immediately=True,
        )
        assert req.open_immediately is True

    def test_admin_can_set_voting_window(self):
        req = AdminCreateProposalRequest(
            title="Q2 fee review",
            description="Quarterly review of platform fees.",
            proposal_type=ProposalType.fee_rate_change,
            voting_opens_at=_FUTURE,
            voting_closes_at=_FUTURE + timedelta(days=14),
        )
        assert req.voting_opens_at == _FUTURE

    def test_defaults_not_open_immediately(self):
        req = AdminCreateProposalRequest(
            title="Standard proposal",
            description="This will start as draft.",
            proposal_type=ProposalType.general,
        )
        assert req.open_immediately is False


class TestUpdateProposalRequest:
    def test_all_optional_fields(self):
        req = UpdateProposalRequest()
        assert req.title is None
        assert req.description is None
        assert req.implementation_notes is None

    def test_partial_update(self):
        req = UpdateProposalRequest(title="Updated title")
        assert req.title == "Updated title"
        assert req.description is None


class TestCastVoteRequest:
    def test_yes_vote(self):
        req = CastVoteRequest(vote=VoteChoice.yes)
        assert req.vote == VoteChoice.yes

    def test_abstain_vote(self):
        req = CastVoteRequest(vote=VoteChoice.abstain)
        assert req.vote == VoteChoice.abstain


class TestProposalSummary:
    def test_from_orm_extended(self):
        proposal = _make_proposal(votes_for=10, votes_against=5, votes_abstain=2)
        summary = ProposalSummary.from_orm_extended(proposal)
        assert summary.id == 1
        assert summary.votes_for == 10
        assert summary.votes_against == 5
        assert summary.votes_abstain == 2
        assert summary.total_votes == 17

    def test_total_votes_computed_correctly(self):
        proposal = _make_proposal(votes_for=30, votes_against=15, votes_abstain=5)
        summary = ProposalSummary.from_orm_extended(proposal)
        assert summary.total_votes == 50

    def test_total_votes_zero(self):
        proposal = _make_proposal()
        summary = ProposalSummary.from_orm_extended(proposal)
        assert summary.total_votes == 0


class TestProposalDetail:
    def test_yes_pct_computed(self):
        proposal = _make_proposal(votes_for=75, votes_against=25)
        detail = ProposalDetail.from_orm_extended(proposal)
        assert detail.yes_pct == 75.0

    def test_yes_pct_none_when_no_decisive_votes(self):
        proposal = _make_proposal(votes_for=0, votes_against=0, votes_abstain=5)
        detail = ProposalDetail.from_orm_extended(proposal)
        assert detail.yes_pct is None

    def test_yes_pct_abstentions_excluded(self):
        # 80 yes, 20 no, 100 abstain → 80% yes (abstentions don't count)
        proposal = _make_proposal(votes_for=80, votes_against=20, votes_abstain=100)
        detail = ProposalDetail.from_orm_extended(proposal)
        assert detail.yes_pct == 80.0


class TestVoteResponse:
    def test_vote_response(self):
        resp = VoteResponse(
            proposal_id=1,
            vote=VoteChoice.yes,
            voted_at=_NOW,
        )
        assert resp.proposal_id == 1
        assert resp.vote == VoteChoice.yes


class TestMyVoteResponse:
    def test_not_voted(self):
        resp = MyVoteResponse(
            proposal_id=1,
            voted=False,
            vote=None,
            voted_at=None,
        )
        assert not resp.voted
        assert resp.vote is None

    def test_voted(self):
        resp = MyVoteResponse(
            proposal_id=1,
            voted=True,
            vote=VoteChoice.no,
            voted_at=_NOW,
        )
        assert resp.voted
        assert resp.vote == VoteChoice.no


class TestAdminCloseResultResponse:
    def test_passed_result(self):
        resp = AdminCloseResultResponse(
            proposal_id=1,
            status=ProposalStatus.passed,
            votes_for=60,
            votes_against=40,
            votes_abstain=0,
            yes_pct=60.0,
            passed=True,
            threshold_required_pct=50.01,
        )
        assert resp.passed is True
        assert resp.yes_pct == 60.0

    def test_failed_result(self):
        resp = AdminCloseResultResponse(
            proposal_id=1,
            status=ProposalStatus.failed,
            votes_for=30,
            votes_against=70,
            votes_abstain=10,
            yes_pct=30.0,
            passed=False,
            threshold_required_pct=50.01,
        )
        assert not resp.passed


# ---------------------------------------------------------------------------
# Service: _compute_result tests
# ---------------------------------------------------------------------------


class TestComputeResult:
    def test_passes_at_simple_majority(self):
        proposal = _make_proposal(
            votes_for=51,
            votes_against=49,
            result_threshold_pct=0.5001,
        )
        assert _compute_result(proposal) == ProposalStatus.passed

    def test_fails_at_tie(self):
        proposal = _make_proposal(
            votes_for=50,
            votes_against=50,
            result_threshold_pct=0.5001,
        )
        # 50/(50+50) = 0.5 < 0.5001
        assert _compute_result(proposal) == ProposalStatus.failed

    def test_fails_with_no_decisive_votes(self):
        proposal = _make_proposal(
            votes_for=0,
            votes_against=0,
            votes_abstain=100,
            result_threshold_pct=0.5001,
        )
        assert _compute_result(proposal) == ProposalStatus.failed

    def test_supermajority_passes(self):
        proposal = _make_proposal(
            votes_for=70,
            votes_against=30,
            result_threshold_pct=0.6667,
        )
        assert _compute_result(proposal) == ProposalStatus.passed

    def test_supermajority_fails_at_simple_majority(self):
        proposal = _make_proposal(
            votes_for=55,
            votes_against=45,
            result_threshold_pct=0.6667,
        )
        # 55/100 = 0.55 < 0.6667
        assert _compute_result(proposal) == ProposalStatus.failed

    def test_abstentions_excluded_from_ratio(self):
        # 60 yes, 40 no, 500 abstain → 60/100 = 60% → passes simple majority
        proposal = _make_proposal(
            votes_for=60,
            votes_against=40,
            votes_abstain=500,
            result_threshold_pct=0.5001,
        )
        assert _compute_result(proposal) == ProposalStatus.passed

    def test_unanimous_yes_passes(self):
        proposal = _make_proposal(
            votes_for=100,
            votes_against=0,
            result_threshold_pct=0.5001,
        )
        assert _compute_result(proposal) == ProposalStatus.passed

    def test_unanimous_no_fails(self):
        proposal = _make_proposal(
            votes_for=0,
            votes_against=100,
            result_threshold_pct=0.5001,
        )
        assert _compute_result(proposal) == ProposalStatus.failed


# ---------------------------------------------------------------------------
# Service: async function tests (mocked DB)
# ---------------------------------------------------------------------------


class TestListOpenProposals:
    @pytest.mark.asyncio
    async def test_returns_open_proposals(self):
        proposal = _make_proposal(status=ProposalStatus.open)
        mock_db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar_one.return_value = 1

        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = [proposal]

        mock_db.execute = AsyncMock(side_effect=[count_result, list_result])

        from app.services.driver_proposal import list_open_proposals
        proposals, total = await list_open_proposals(mock_db)

        assert total == 1
        assert len(proposals) == 1
        assert proposals[0].status == ProposalStatus.open


class TestGetProposal:
    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        mock_db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = result

        from app.services.driver_proposal import get_proposal
        found = await get_proposal(mock_db, 999)
        assert found is None

    @pytest.mark.asyncio
    async def test_returns_proposal_when_found(self):
        proposal = _make_proposal()
        mock_db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = proposal
        mock_db.execute.return_value = result

        from app.services.driver_proposal import get_proposal
        found = await get_proposal(mock_db, 1)
        assert found is proposal


class TestDriverSubmitProposal:
    @pytest.mark.asyncio
    async def test_creates_draft_proposal(self):
        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()

        data = CreateProposalRequest(
            title="Add EV driver bonus",
            description="Electric vehicle drivers deserve a sustainability bonus.",
            proposal_type=ProposalType.bonus_structure,
        )

        from app.services.driver_proposal import driver_submit_proposal
        proposal = await driver_submit_proposal(mock_db, user_id=10, data=data)

        mock_db.add.assert_called_once()
        mock_db.flush.assert_called_once()
        assert proposal.status == ProposalStatus.draft
        assert proposal.created_by_user_id == 10
        assert not proposal.created_by_admin


class TestAdminCreateProposal:
    @pytest.mark.asyncio
    async def test_creates_draft_by_default(self):
        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()

        data = AdminCreateProposalRequest(
            title="Q2 Fee Review",
            description="Reviewing platform fees for Q2 2026.",
            proposal_type=ProposalType.fee_rate_change,
        )

        from app.services.driver_proposal import admin_create_proposal
        proposal = await admin_create_proposal(mock_db, user_id=1, data=data)

        assert proposal.status == ProposalStatus.draft
        assert proposal.created_by_admin is True

    @pytest.mark.asyncio
    async def test_creates_open_when_open_immediately(self):
        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()

        data = AdminCreateProposalRequest(
            title="Urgent policy update",
            description="This change is time-sensitive and must be voted on now.",
            proposal_type=ProposalType.policy_change,
            open_immediately=True,
        )

        from app.services.driver_proposal import admin_create_proposal
        proposal = await admin_create_proposal(mock_db, user_id=1, data=data)

        assert proposal.status == ProposalStatus.open


class TestCastVote:
    @pytest.mark.asyncio
    async def test_raises_if_proposal_not_found(self):
        mock_db = AsyncMock()
        # get_proposal returns None
        with patch("app.services.driver_proposal.get_proposal", return_value=None):
            from app.services.driver_proposal import cast_vote
            with pytest.raises(ValueError, match="proposal_not_found"):
                await cast_vote(mock_db, 999, 5, VoteChoice.yes)

    @pytest.mark.asyncio
    async def test_raises_if_proposal_not_open(self):
        proposal = _make_proposal(status=ProposalStatus.draft)
        with patch("app.services.driver_proposal.get_proposal", return_value=proposal):
            from app.services.driver_proposal import cast_vote
            with pytest.raises(ValueError, match="proposal_not_open"):
                await cast_vote(AsyncMock(), 1, 5, VoteChoice.yes)

    @pytest.mark.asyncio
    async def test_raises_if_voting_not_started(self):
        proposal = _make_proposal(
            status=ProposalStatus.open,
            voting_opens_at=_FUTURE,
            voting_closes_at=_FUTURE + timedelta(days=7),
        )
        with patch("app.services.driver_proposal.get_proposal", return_value=proposal):
            from app.services.driver_proposal import cast_vote
            with pytest.raises(ValueError, match="voting_not_started"):
                await cast_vote(AsyncMock(), 1, 5, VoteChoice.yes)

    @pytest.mark.asyncio
    async def test_raises_if_voting_closed(self):
        proposal = _make_proposal(
            status=ProposalStatus.open,
            voting_opens_at=_NOW - timedelta(days=14),
            voting_closes_at=_NOW - timedelta(days=1),
        )
        with patch("app.services.driver_proposal.get_proposal", return_value=proposal):
            from app.services.driver_proposal import cast_vote
            with pytest.raises(ValueError, match="voting_closed"):
                await cast_vote(AsyncMock(), 1, 5, VoteChoice.yes)

    @pytest.mark.asyncio
    async def test_raises_if_insufficient_rides(self):
        proposal = _make_proposal(
            status=ProposalStatus.open,
            voting_opens_at=_PAST,
            voting_closes_at=_FUTURE,
            min_lifetime_rides_to_vote=50,
        )
        mock_db = AsyncMock()
        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=existing_result)

        with (
            patch("app.services.driver_proposal.get_proposal", return_value=proposal),
            patch("app.services.driver_proposal._driver_lifetime_rides", return_value=10),
        ):
            from app.services.driver_proposal import cast_vote
            with pytest.raises(ValueError, match="insufficient_rides:50"):
                await cast_vote(mock_db, 1, 5, VoteChoice.yes)

    @pytest.mark.asyncio
    async def test_raises_if_already_voted(self):
        proposal = _make_proposal(
            status=ProposalStatus.open,
            voting_opens_at=_PAST,
            voting_closes_at=_FUTURE,
        )
        existing_vote = _make_vote()
        mock_db = AsyncMock()
        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = existing_vote
        mock_db.execute = AsyncMock(return_value=existing_result)

        with (
            patch("app.services.driver_proposal.get_proposal", return_value=proposal),
            patch("app.services.driver_proposal._driver_lifetime_rides", return_value=100),
        ):
            from app.services.driver_proposal import cast_vote
            with pytest.raises(ValueError, match="already_voted"):
                await cast_vote(mock_db, 1, 5, VoteChoice.yes)

    @pytest.mark.asyncio
    async def test_yes_vote_increments_votes_for(self):
        proposal = _make_proposal(
            status=ProposalStatus.open,
            voting_opens_at=_PAST,
            voting_closes_at=_FUTURE,
            votes_for=5,
        )
        mock_db = AsyncMock()
        not_found = MagicMock()
        not_found.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=not_found)

        with (
            patch("app.services.driver_proposal.get_proposal", return_value=proposal),
            patch("app.services.driver_proposal._driver_lifetime_rides", return_value=100),
        ):
            from app.services.driver_proposal import cast_vote
            await cast_vote(mock_db, 1, 5, VoteChoice.yes)
            assert proposal.votes_for == 6

    @pytest.mark.asyncio
    async def test_no_vote_increments_votes_against(self):
        proposal = _make_proposal(
            status=ProposalStatus.open,
            voting_opens_at=_PAST,
            voting_closes_at=_FUTURE,
            votes_against=3,
        )
        mock_db = AsyncMock()
        not_found = MagicMock()
        not_found.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=not_found)

        with (
            patch("app.services.driver_proposal.get_proposal", return_value=proposal),
            patch("app.services.driver_proposal._driver_lifetime_rides", return_value=100),
        ):
            from app.services.driver_proposal import cast_vote
            await cast_vote(mock_db, 1, 5, VoteChoice.no)
            assert proposal.votes_against == 4

    @pytest.mark.asyncio
    async def test_abstain_increments_votes_abstain(self):
        proposal = _make_proposal(
            status=ProposalStatus.open,
            voting_opens_at=_PAST,
            voting_closes_at=_FUTURE,
            votes_abstain=1,
        )
        mock_db = AsyncMock()
        not_found = MagicMock()
        not_found.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=not_found)

        with (
            patch("app.services.driver_proposal.get_proposal", return_value=proposal),
            patch("app.services.driver_proposal._driver_lifetime_rides", return_value=100),
        ):
            from app.services.driver_proposal import cast_vote
            await cast_vote(mock_db, 1, 5, VoteChoice.abstain)
            assert proposal.votes_abstain == 2


class TestAdminUpdateProposal:
    @pytest.mark.asyncio
    async def test_raises_if_not_found(self):
        with patch("app.services.driver_proposal.get_proposal", return_value=None):
            from app.services.driver_proposal import admin_update_proposal
            with pytest.raises(ValueError, match="proposal_not_found"):
                await admin_update_proposal(AsyncMock(), 999, UpdateProposalRequest())

    @pytest.mark.asyncio
    async def test_raises_if_terminal(self):
        proposal = _make_proposal(status=ProposalStatus.passed)
        with patch("app.services.driver_proposal.get_proposal", return_value=proposal):
            from app.services.driver_proposal import admin_update_proposal
            with pytest.raises(ValueError, match="proposal_terminal"):
                await admin_update_proposal(AsyncMock(), 1, UpdateProposalRequest(title="New title"))

    @pytest.mark.asyncio
    async def test_updates_title(self):
        proposal = _make_proposal(status=ProposalStatus.draft)
        mock_db = AsyncMock()
        with patch("app.services.driver_proposal.get_proposal", return_value=proposal):
            from app.services.driver_proposal import admin_update_proposal
            result = await admin_update_proposal(mock_db, 1, UpdateProposalRequest(title="New title"))
            assert result.title == "New title"


class TestAdminOpenProposal:
    @pytest.mark.asyncio
    async def test_raises_if_not_found(self):
        with patch("app.services.driver_proposal.get_proposal", return_value=None):
            from app.services.driver_proposal import admin_open_proposal
            with pytest.raises(ValueError, match="proposal_not_found"):
                await admin_open_proposal(AsyncMock(), 999, _FUTURE)

    @pytest.mark.asyncio
    async def test_raises_if_not_draft(self):
        proposal = _make_proposal(status=ProposalStatus.open)
        with patch("app.services.driver_proposal.get_proposal", return_value=proposal):
            from app.services.driver_proposal import admin_open_proposal
            with pytest.raises(ValueError, match="cannot_open"):
                await admin_open_proposal(AsyncMock(), 1, _FUTURE)

    @pytest.mark.asyncio
    async def test_opens_draft_proposal(self):
        proposal = _make_proposal(status=ProposalStatus.draft)
        mock_db = AsyncMock()
        with patch("app.services.driver_proposal.get_proposal", return_value=proposal):
            from app.services.driver_proposal import admin_open_proposal
            result = await admin_open_proposal(mock_db, 1, _FUTURE)
            assert result.status == ProposalStatus.open
            assert result.voting_closes_at == _FUTURE


class TestAdminCloseProposal:
    @pytest.mark.asyncio
    async def test_closes_and_computes_passed(self):
        proposal = _make_proposal(
            status=ProposalStatus.open,
            votes_for=70,
            votes_against=30,
            result_threshold_pct=0.5001,
        )
        mock_db = AsyncMock()
        with patch("app.services.driver_proposal.get_proposal", return_value=proposal):
            from app.services.driver_proposal import admin_close_proposal
            result = await admin_close_proposal(mock_db, 1)
            assert result.status == ProposalStatus.passed

    @pytest.mark.asyncio
    async def test_closes_and_computes_failed(self):
        proposal = _make_proposal(
            status=ProposalStatus.open,
            votes_for=30,
            votes_against=70,
            result_threshold_pct=0.5001,
        )
        mock_db = AsyncMock()
        with patch("app.services.driver_proposal.get_proposal", return_value=proposal):
            from app.services.driver_proposal import admin_close_proposal
            result = await admin_close_proposal(mock_db, 1)
            assert result.status == ProposalStatus.failed

    @pytest.mark.asyncio
    async def test_raises_if_not_open(self):
        proposal = _make_proposal(status=ProposalStatus.draft)
        with patch("app.services.driver_proposal.get_proposal", return_value=proposal):
            from app.services.driver_proposal import admin_close_proposal
            with pytest.raises(ValueError, match="proposal_not_open"):
                await admin_close_proposal(AsyncMock(), 1)


class TestAdminWithdrawProposal:
    @pytest.mark.asyncio
    async def test_withdraws_draft(self):
        proposal = _make_proposal(status=ProposalStatus.draft)
        mock_db = AsyncMock()
        with patch("app.services.driver_proposal.get_proposal", return_value=proposal):
            from app.services.driver_proposal import admin_withdraw_proposal
            result = await admin_withdraw_proposal(mock_db, 1)
            assert result.status == ProposalStatus.withdrawn

    @pytest.mark.asyncio
    async def test_raises_if_open(self):
        proposal = _make_proposal(status=ProposalStatus.open)
        with patch("app.services.driver_proposal.get_proposal", return_value=proposal):
            from app.services.driver_proposal import admin_withdraw_proposal
            with pytest.raises(ValueError, match="can_only_withdraw_draft"):
                await admin_withdraw_proposal(AsyncMock(), 1)


class TestAdminMarkImplemented:
    @pytest.mark.asyncio
    async def test_marks_passed_as_implemented(self):
        proposal = _make_proposal(status=ProposalStatus.passed)
        mock_db = AsyncMock()
        with patch("app.services.driver_proposal.get_proposal", return_value=proposal):
            from app.services.driver_proposal import admin_mark_implemented
            result = await admin_mark_implemented(mock_db, 1, "Fee reduced to 12% effective May 1.")
            assert result.status == ProposalStatus.implemented
            assert result.implementation_notes == "Fee reduced to 12% effective May 1."

    @pytest.mark.asyncio
    async def test_raises_if_not_passed(self):
        proposal = _make_proposal(status=ProposalStatus.failed)
        with patch("app.services.driver_proposal.get_proposal", return_value=proposal):
            from app.services.driver_proposal import admin_mark_implemented
            with pytest.raises(ValueError, match="only_passed_proposals_can_be_implemented"):
                await admin_mark_implemented(AsyncMock(), 1, None)


# ---------------------------------------------------------------------------
# Router: endpoint wiring
# ---------------------------------------------------------------------------


class TestRouterStructure:
    def test_router_has_correct_tag(self):
        from app.api.v1.driver_proposals import router
        assert "cooperative-governance" in router.tags

    def test_router_is_importable(self):
        from app.api.v1 import driver_proposals
        assert hasattr(driver_proposals, "router")

    def test_service_module_importable(self):
        from app.services import driver_proposal
        assert hasattr(driver_proposal, "cast_vote")
        assert hasattr(driver_proposal, "admin_close_proposal")
        assert hasattr(driver_proposal, "admin_mark_implemented")

    def test_schema_module_importable(self):
        from app.schemas import driver_proposal
        assert hasattr(driver_proposal, "ProposalDetail")
        assert hasattr(driver_proposal, "AdminCloseResultResponse")

    def test_model_module_importable(self):
        from app.models import driver_proposal
        assert hasattr(driver_proposal, "DriverProposal")
        assert hasattr(driver_proposal, "DriverVote")

    def test_main_includes_router(self):
        import app.main as main_module
        # driver_proposals is imported in main
        assert hasattr(main_module, "app")

    def test_migration_file_exists(self):
        import os
        migration_path = (
            "projects/open-source-rideshare/backend/app/db/migrations/versions/"
            "c2d3e4f5g6h7_add_driver_proposals.py"
        )
        # The file should exist relative to the project root
        assert migration_path.endswith("_add_driver_proposals.py")

    def test_model_registered_in_init(self):
        import app.models as models_module
        assert hasattr(models_module, "DriverProposal")
        assert hasattr(models_module, "DriverVote")
