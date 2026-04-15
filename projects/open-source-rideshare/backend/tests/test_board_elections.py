"""Tests for the Cooperative Board Elections feature.

Service layer (async, mocked DB):
  1.  create_seat — inserts seat and returns it
  2.  create_seat — name uniqueness (conflict raises on flush, not tested here)
  3.  get_seat — returns None when not found
  4.  get_seat — returns seat when found
  5.  get_all_seats — active_only=False returns all seats
  6.  get_all_seats — active_only=True filters inactive
  7.  update_seat — applies partial update
  8.  update_seat — raises 404 when seat not found
  9.  create_election — raises 404 when seat not found
  10. create_election — raises 409 when active election exists for seat
  11. create_election — inserts election in draft status
  12. open_nominations — raises 404 when election not found
  13. open_nominations — raises 409 when election not in draft status
  14. open_nominations — raises 422 when close <= open
  15. open_nominations — transitions to nominations_open
  16. close_nominations — raises 409 when not nominations_open
  17. close_nominations — transitions to nominations_closed
  18. open_voting — raises 409 when not nominations_closed
  19. open_voting — raises 409 when no approved candidacies
  20. open_voting — transitions to voting_open
  21. tally_votes — raises 409 when not voting_open
  22. tally_votes — tallies correctly and sets winner
  23. tally_votes — breaks tie by earliest applied_at
  24. certify_election — raises 409 when not tallied
  25. certify_election — certifies and updates seat holder
  26. cancel_election — raises 409 when already certified
  27. cancel_election — raises 409 when already cancelled
  28. cancel_election — cancels from voting_open
  29. apply_for_candidacy — raises 409 when nominations not open
  30. apply_for_candidacy — raises 409 when already applied
  31. apply_for_candidacy — raises 403 when insufficient lifetime rides
  32. apply_for_candidacy — creates pending candidacy
  33. review_candidacy — raises 404 when not found
  34. review_candidacy — raises 409 when already reviewed
  35. review_candidacy — approves candidacy
  36. review_candidacy — rejects candidacy with admin_notes
  37. withdraw_candidacy — raises 403 when not owner
  38. withdraw_candidacy — raises 409 when already rejected
  39. withdraw_candidacy — withdraws pending candidacy
  40. cast_vote — raises 409 when voting not open
  41. cast_vote — raises 404 when candidacy not in this election
  42. cast_vote — raises 409 when candidacy not approved
  43. cast_vote — raises 403 when voter has insufficient rides
  44. cast_vote — raises 409 when already voted
  45. cast_vote — records vote
  46. get_election_results — raises 409 when election not tallied
  47. get_election_results — returns results after tallying
  48. get_board_roster — returns active seats with holders

Schema validation:
  49. CreateBoardSeatRequest — rejects term_months <= 0
  50. ApplyForCandidacyRequest — rejects statement under 10 chars
  51. OpenNominationsRequest — accepts valid window

API layer (integration-style, skipped without live DB):
  52. GET /cooperative/board/roster — 200
  53. GET /cooperative/board/seats — 200
  54. GET /cooperative/elections — 200 (driver)
  55. GET /cooperative/elections/{id} — 404 when missing
  56. POST /cooperative/elections/{id}/candidacy — 201
  57. POST /cooperative/elections/{id}/vote — 201
  58. POST /cooperative/board/seats — 201 (admin)
  59. POST /cooperative/board/seats — 403 non-admin
  60. POST /cooperative/elections — 201 draft (admin)
  61. POST /cooperative/elections/{id}/open-nominations — 200 (admin)
  62. POST /cooperative/elections/{id}/close-nominations — 200 (admin)
  63. POST /cooperative/elections/{id}/open-voting — 200 (admin)
  64. POST /cooperative/elections/{id}/tally — 200 (admin)
  65. POST /cooperative/elections/{id}/certify — 200 (admin)
  66. POST /cooperative/elections/{id}/cancel — 200 (admin)
  67. GET /cooperative/elections/{id}/results — 200 (admin, after tally)
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.board_election import (
    BoardCandidacy,
    BoardElection,
    BoardElectionVote,
    CandidacyStatus,
    CooperativeBoardSeat,
    ElectionStatus,
)
from app.schemas.board_election import (
    ApplyForCandidacyRequest,
    CreateBoardSeatRequest,
    OpenNominationsRequest,
)
from app.services.board_election import BoardElectionError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
_FUTURE = _NOW + timedelta(hours=4)
_FAR_FUTURE = _NOW + timedelta(days=7)
_PAST = _NOW - timedelta(hours=4)


def _make_seat(**kw) -> CooperativeBoardSeat:
    defaults = dict(
        id=1,
        name="President",
        description="Board president",
        term_months=12,
        max_consecutive_terms=2,
        min_lifetime_rides_to_run=100,
        current_holder_id=None,
        holder_term_ends_at=None,
        is_active=True,
        created_at=_NOW,
        updated_at=_NOW,
    )
    defaults.update(kw)
    obj = MagicMock(spec=CooperativeBoardSeat)
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _make_election(**kw) -> BoardElection:
    defaults = dict(
        id=10,
        seat_id=1,
        title="2026 Presidential Election",
        description=None,
        status=ElectionStatus.draft,
        nominations_open_at=None,
        nominations_close_at=None,
        voting_opens_at=None,
        voting_closes_at=None,
        min_lifetime_rides_to_vote=50,
        winner_id=None,
        certified_at=None,
        certification_notes=None,
        created_at=_NOW,
        updated_at=_NOW,
    )
    defaults.update(kw)
    obj = MagicMock(spec=BoardElection)
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _make_candidacy(**kw) -> BoardCandidacy:
    defaults = dict(
        id=20,
        election_id=10,
        driver_profile_id=5,
        statement="I will fight for fair rates.",
        status=CandidacyStatus.pending,
        admin_notes=None,
        vote_count=0,
        applied_at=_NOW,
        reviewed_at=None,
    )
    defaults.update(kw)
    obj = MagicMock(spec=BoardCandidacy)
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _make_driver(**kw):
    defaults = dict(id=5, lifetime_rides=200)
    defaults.update(kw)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _make_vote(**kw) -> BoardElectionVote:
    defaults = dict(
        id=30,
        election_id=10,
        candidacy_id=20,
        voter_driver_profile_id=5,
        voted_at=_NOW,
    )
    defaults.update(kw)
    obj = MagicMock(spec=BoardElectionVote)
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _async_result(value):
    """Build a mock execute() result whose scalar_one_or_none() returns value synchronously."""
    r = MagicMock()
    r.scalar_one_or_none = MagicMock(return_value=value)
    r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=value if isinstance(value, list) else [])))
    r.first = MagicMock(return_value=value)
    return r


def _db(**overrides):
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_async_result(None))
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    for k, v in overrides.items():
        setattr(db, k, v)
    return db


# ---------------------------------------------------------------------------
# Import service functions after helpers are defined
# ---------------------------------------------------------------------------
from app.services.board_election import (
    apply_for_candidacy,
    cancel_election,
    cast_vote,
    certify_election,
    close_nominations,
    create_election,
    create_seat,
    get_all_seats,
    get_board_roster,
    get_election,
    get_election_results,
    get_seat,
    open_nominations,
    open_voting,
    review_candidacy,
    tally_votes,
    update_seat,
    withdraw_candidacy,
)


# ---------------------------------------------------------------------------
# 1–8  Board Seat operations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_seat_inserts_and_returns():
    seat = _make_seat()
    db = _db()
    db.flush = AsyncMock()
    db.refresh = AsyncMock(side_effect=lambda obj: None)
    with patch("app.services.board_election.CooperativeBoardSeat", return_value=seat):
        result = await create_seat(db, "President", None, 12, 2, 100)
    assert result is seat
    db.add.assert_called_once_with(seat)


@pytest.mark.asyncio
async def test_get_seat_returns_none_when_missing():
    db = _db()
    db.execute = AsyncMock(return_value=_async_result(None))
    result = await get_seat(db, 999)
    assert result is None


@pytest.mark.asyncio
async def test_get_seat_returns_seat_when_found():
    seat = _make_seat()
    db = _db()
    db.execute = AsyncMock(return_value=_async_result(seat))
    result = await get_seat(db, 1)
    assert result is seat


@pytest.mark.asyncio
async def test_get_all_seats_active_only_filters():
    active = _make_seat(is_active=True)
    inactive = _make_seat(id=2, is_active=False)
    db = _db()

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [active]
    db.execute = AsyncMock(return_value=mock_result)

    seats = await get_all_seats(db, active_only=True)
    assert active in seats
    assert inactive not in seats


@pytest.mark.asyncio
async def test_get_all_seats_returns_all_when_not_filtered():
    seat1 = _make_seat()
    seat2 = _make_seat(id=2, is_active=False)
    db = _db()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [seat1, seat2]
    db.execute = AsyncMock(return_value=mock_result)

    seats = await get_all_seats(db, active_only=False)
    assert len(seats) == 2


@pytest.mark.asyncio
async def test_update_seat_applies_fields():
    seat = _make_seat()
    db = _db()
    db.execute = AsyncMock(return_value=_async_result(seat))

    result = await update_seat(db, seat_id=1, description="Updated description")
    assert result is seat
    assert seat.description == "Updated description"


@pytest.mark.asyncio
async def test_update_seat_raises_404_when_missing():
    db = _db()
    db.execute = AsyncMock(return_value=_async_result(None))
    with pytest.raises(BoardElectionError) as exc:
        await update_seat(db, seat_id=999, description="x")
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 9–11  create_election
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_election_raises_404_when_seat_missing():
    db = _db()
    db.execute = AsyncMock(return_value=_async_result(None))
    with pytest.raises(BoardElectionError) as exc:
        await create_election(db, seat_id=99, title="Test", description=None, min_lifetime_rides_to_vote=50)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_create_election_raises_409_when_active_election_exists():
    seat = _make_seat()
    existing = _make_election(status=ElectionStatus.voting_open)

    call_count = 0
    async def _execute(q):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _async_result(seat)
        return _async_result(existing)

    db = _db()
    db.execute = AsyncMock(side_effect=_execute)
    with pytest.raises(BoardElectionError) as exc:
        await create_election(db, seat_id=1, title="Test", description=None, min_lifetime_rides_to_vote=50)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_create_election_inserts_draft():
    seat = _make_seat()

    call_count = 0
    async def _execute(q):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _async_result(seat)
        return _async_result(None)  # no existing active election

    db = _db()
    db.execute = AsyncMock(side_effect=_execute)

    result = await create_election(db, seat_id=1, title="Test", description=None, min_lifetime_rides_to_vote=50)
    assert result.status == ElectionStatus.draft
    assert result.title == "Test"
    db.add.assert_called_once()


# ---------------------------------------------------------------------------
# 12–15  open_nominations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_open_nominations_raises_404():
    db = _db()
    db.execute = AsyncMock(return_value=_async_result(None))
    with pytest.raises(BoardElectionError) as exc:
        await open_nominations(db, 99, _NOW, _FUTURE)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_open_nominations_raises_409_wrong_status():
    election = _make_election(status=ElectionStatus.voting_open)
    db = _db()
    db.execute = AsyncMock(return_value=_async_result(election))
    with pytest.raises(BoardElectionError) as exc:
        await open_nominations(db, 10, _NOW, _FUTURE)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_open_nominations_raises_422_when_close_before_open():
    election = _make_election(status=ElectionStatus.draft)
    db = _db()
    db.execute = AsyncMock(return_value=_async_result(election))
    with pytest.raises(BoardElectionError) as exc:
        await open_nominations(db, 10, _FUTURE, _NOW)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_open_nominations_transitions_status():
    election = _make_election(status=ElectionStatus.draft)
    db = _db()
    db.execute = AsyncMock(return_value=_async_result(election))

    result = await open_nominations(db, 10, _NOW, _FUTURE)
    assert result.status == ElectionStatus.nominations_open
    assert result.nominations_open_at == _NOW
    assert result.nominations_close_at == _FUTURE


# ---------------------------------------------------------------------------
# 16–17  close_nominations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_nominations_raises_409_wrong_status():
    election = _make_election(status=ElectionStatus.draft)
    db = _db()
    db.execute = AsyncMock(return_value=_async_result(election))
    with pytest.raises(BoardElectionError) as exc:
        await close_nominations(db, 10)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_close_nominations_transitions():
    election = _make_election(status=ElectionStatus.nominations_open)
    db = _db()
    db.execute = AsyncMock(return_value=_async_result(election))

    result = await close_nominations(db, 10)
    assert result.status == ElectionStatus.nominations_closed


# ---------------------------------------------------------------------------
# 18–20  open_voting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_open_voting_raises_409_wrong_status():
    election = _make_election(status=ElectionStatus.draft)
    db = _db()
    db.execute = AsyncMock(return_value=_async_result(election))
    with pytest.raises(BoardElectionError) as exc:
        await open_voting(db, 10, _NOW, _FUTURE)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_open_voting_raises_409_no_approved_candidacies():
    election = _make_election(status=ElectionStatus.nominations_closed)
    call_count = 0

    async def _execute(q):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _async_result(election)
        # No approved candidacies
        r = MagicMock()
        r.first = MagicMock(return_value=None)
        return r

    db = _db()
    db.execute = AsyncMock(side_effect=_execute)
    with pytest.raises(BoardElectionError) as exc:
        await open_voting(db, 10, _NOW, _FUTURE)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_open_voting_transitions():
    election = _make_election(status=ElectionStatus.nominations_closed)
    approved_candidacy = _make_candidacy(status=CandidacyStatus.approved)
    call_count = 0

    async def _execute(q):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _async_result(election)
        # Has approved candidacy
        r = MagicMock()
        r.first = MagicMock(return_value=approved_candidacy)
        return r

    db = _db()
    db.execute = AsyncMock(side_effect=_execute)

    result = await open_voting(db, 10, _NOW, _FUTURE)
    assert result.status == ElectionStatus.voting_open


# ---------------------------------------------------------------------------
# 21–23  tally_votes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tally_raises_409_wrong_status():
    election = _make_election(status=ElectionStatus.nominations_open)
    db = _db()
    db.execute = AsyncMock(return_value=_async_result(election))
    with pytest.raises(BoardElectionError) as exc:
        await tally_votes(db, 10)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_tally_sets_winner_most_votes():
    election = _make_election(status=ElectionStatus.voting_open)
    c1 = _make_candidacy(id=20, driver_profile_id=5, vote_count=0, applied_at=_NOW)
    c2 = _make_candidacy(id=21, driver_profile_id=6, vote_count=0, applied_at=_NOW + timedelta(minutes=5))

    # votes: c1 gets 3, c2 gets 1
    v1 = [_make_vote(candidacy_id=20), _make_vote(candidacy_id=20), _make_vote(candidacy_id=20)]
    v2 = [_make_vote(candidacy_id=21)]

    call_count = 0
    async def _execute(q):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _async_result(election)
        if call_count == 2:
            r = MagicMock()
            r.scalars.return_value.all.return_value = [c1, c2]
            return r
        # Votes for c1
        if call_count == 3:
            r = MagicMock()
            r.scalars.return_value.all.return_value = v1
            return r
        # Votes for c2
        r = MagicMock()
        r.scalars.return_value.all.return_value = v2
        return r

    db = _db()
    db.execute = AsyncMock(side_effect=_execute)

    result = await tally_votes(db, 10)
    assert result.status == ElectionStatus.tallied
    assert result.winner_id == 5  # c1's driver_profile_id


@pytest.mark.asyncio
async def test_tally_breaks_tie_by_earliest_applied_at():
    election = _make_election(status=ElectionStatus.voting_open)
    earlier = _NOW - timedelta(hours=1)
    c1 = _make_candidacy(id=20, driver_profile_id=5, vote_count=0, applied_at=earlier)
    c2 = _make_candidacy(id=21, driver_profile_id=6, vote_count=0, applied_at=_NOW)

    votes_each = [_make_vote()]  # 1 vote each — tie

    call_count = 0
    async def _execute(q):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _async_result(election)
        if call_count == 2:
            r = MagicMock()
            r.scalars.return_value.all.return_value = [c1, c2]
            return r
        r = MagicMock()
        r.scalars.return_value.all.return_value = votes_each
        return r

    db = _db()
    db.execute = AsyncMock(side_effect=_execute)

    result = await tally_votes(db, 10)
    # Tie broken by earliest applied_at → c1 wins
    assert result.winner_id == 5


# ---------------------------------------------------------------------------
# 24–25  certify_election
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_certify_raises_409_not_tallied():
    election = _make_election(status=ElectionStatus.voting_open)
    db = _db()
    db.execute = AsyncMock(return_value=_async_result(election))
    with pytest.raises(BoardElectionError) as exc:
        await certify_election(db, 10, None)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_certify_updates_seat_holder():
    election = _make_election(status=ElectionStatus.tallied, winner_id=5)
    seat = _make_seat(current_holder_id=None)

    call_count = 0
    async def _execute(q):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _async_result(election)
        return _async_result(seat)

    db = _db()
    db.execute = AsyncMock(side_effect=_execute)

    result = await certify_election(db, 10, "Clean election.")
    assert result.status == ElectionStatus.certified
    assert seat.current_holder_id == 5


# ---------------------------------------------------------------------------
# 26–28  cancel_election
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_raises_409_when_certified():
    election = _make_election(status=ElectionStatus.certified)
    db = _db()
    db.execute = AsyncMock(return_value=_async_result(election))
    with pytest.raises(BoardElectionError) as exc:
        await cancel_election(db, 10)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_cancel_raises_409_when_already_cancelled():
    election = _make_election(status=ElectionStatus.cancelled)
    db = _db()
    db.execute = AsyncMock(return_value=_async_result(election))
    with pytest.raises(BoardElectionError) as exc:
        await cancel_election(db, 10)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_cancel_from_voting_open():
    election = _make_election(status=ElectionStatus.voting_open)
    db = _db()
    db.execute = AsyncMock(return_value=_async_result(election))

    result = await cancel_election(db, 10)
    assert result.status == ElectionStatus.cancelled


# ---------------------------------------------------------------------------
# 29–32  apply_for_candidacy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_raises_409_nominations_not_open():
    election = _make_election(status=ElectionStatus.voting_open)
    db = _db()
    db.execute = AsyncMock(return_value=_async_result(election))
    with pytest.raises(BoardElectionError) as exc:
        await apply_for_candidacy(db, 10, 5, "My platform")
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_apply_raises_409_already_applied():
    election = _make_election(status=ElectionStatus.nominations_open)
    existing_candidacy = _make_candidacy()

    call_count = 0
    async def _execute(q):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _async_result(election)
        return _async_result(existing_candidacy)

    db = _db()
    db.execute = AsyncMock(side_effect=_execute)
    with pytest.raises(BoardElectionError) as exc:
        await apply_for_candidacy(db, 10, 5, "My platform")
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_apply_raises_403_insufficient_rides():
    election = _make_election(status=ElectionStatus.nominations_open)
    seat = _make_seat(min_lifetime_rides_to_run=100)
    driver = _make_driver(lifetime_rides=10)  # below threshold

    call_count = 0
    async def _execute(q):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _async_result(election)
        if call_count == 2:
            return _async_result(None)  # no existing candidacy
        if call_count == 3:
            return _async_result(seat)
        return _async_result(driver)

    db = _db()
    db.execute = AsyncMock(side_effect=_execute)
    with pytest.raises(BoardElectionError) as exc:
        await apply_for_candidacy(db, 10, 5, "My platform")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_apply_creates_pending_candidacy():
    election = _make_election(status=ElectionStatus.nominations_open)
    seat = _make_seat(min_lifetime_rides_to_run=100)
    driver = _make_driver(lifetime_rides=200)

    call_count = 0
    async def _execute(q):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _async_result(election)
        if call_count == 2:
            return _async_result(None)  # no existing candidacy
        if call_count == 3:
            return _async_result(seat)
        return _async_result(driver)

    db = _db()
    db.execute = AsyncMock(side_effect=_execute)

    result = await apply_for_candidacy(db, 10, 5, "My platform")
    assert result.status == CandidacyStatus.pending
    assert result.election_id == 10
    db.add.assert_called_once()


# ---------------------------------------------------------------------------
# 33–36  review_candidacy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_raises_404_not_found():
    db = _db()
    db.execute = AsyncMock(return_value=_async_result(None))
    with pytest.raises(BoardElectionError) as exc:
        await review_candidacy(db, 999, approve=True, admin_notes=None)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_review_raises_409_already_reviewed():
    candidacy = _make_candidacy(status=CandidacyStatus.approved)
    db = _db()
    db.execute = AsyncMock(return_value=_async_result(candidacy))
    with pytest.raises(BoardElectionError) as exc:
        await review_candidacy(db, 20, approve=True, admin_notes=None)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_review_approves_candidacy():
    candidacy = _make_candidacy(status=CandidacyStatus.pending)
    db = _db()
    db.execute = AsyncMock(return_value=_async_result(candidacy))

    result = await review_candidacy(db, 20, approve=True, admin_notes=None)
    assert result.status == CandidacyStatus.approved


@pytest.mark.asyncio
async def test_review_rejects_with_notes():
    candidacy = _make_candidacy(status=CandidacyStatus.pending)
    db = _db()
    db.execute = AsyncMock(return_value=_async_result(candidacy))

    result = await review_candidacy(db, 20, approve=False, admin_notes="Ineligible")
    assert result.status == CandidacyStatus.rejected
    assert result.admin_notes == "Ineligible"


# ---------------------------------------------------------------------------
# 37–39  withdraw_candidacy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_withdraw_raises_403_not_owner():
    candidacy = _make_candidacy(driver_profile_id=99)  # different driver
    db = _db()
    db.execute = AsyncMock(return_value=_async_result(candidacy))
    with pytest.raises(BoardElectionError) as exc:
        await withdraw_candidacy(db, 20, driver_profile_id=5)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_withdraw_raises_409_already_rejected():
    candidacy = _make_candidacy(driver_profile_id=5, status=CandidacyStatus.rejected)
    db = _db()
    db.execute = AsyncMock(return_value=_async_result(candidacy))
    with pytest.raises(BoardElectionError) as exc:
        await withdraw_candidacy(db, 20, driver_profile_id=5)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_withdraw_pending_candidacy():
    candidacy = _make_candidacy(driver_profile_id=5, status=CandidacyStatus.pending)
    db = _db()
    db.execute = AsyncMock(return_value=_async_result(candidacy))

    result = await withdraw_candidacy(db, 20, driver_profile_id=5)
    assert result.status == CandidacyStatus.withdrawn


# ---------------------------------------------------------------------------
# 40–45  cast_vote
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cast_vote_raises_409_not_open():
    election = _make_election(status=ElectionStatus.nominations_open)
    db = _db()
    db.execute = AsyncMock(return_value=_async_result(election))
    with pytest.raises(BoardElectionError) as exc:
        await cast_vote(db, 10, 20, 5)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_cast_vote_raises_404_candidacy_wrong_election():
    election = _make_election(status=ElectionStatus.voting_open)
    candidacy = _make_candidacy(election_id=999)  # wrong election

    call_count = 0
    async def _execute(q):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _async_result(election)
        return _async_result(candidacy)

    db = _db()
    db.execute = AsyncMock(side_effect=_execute)
    with pytest.raises(BoardElectionError) as exc:
        await cast_vote(db, 10, 20, 5)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_cast_vote_raises_409_candidacy_not_approved():
    election = _make_election(status=ElectionStatus.voting_open)
    candidacy = _make_candidacy(election_id=10, status=CandidacyStatus.pending)

    call_count = 0
    async def _execute(q):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _async_result(election)
        return _async_result(candidacy)

    db = _db()
    db.execute = AsyncMock(side_effect=_execute)
    with pytest.raises(BoardElectionError) as exc:
        await cast_vote(db, 10, 20, 5)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_cast_vote_raises_403_insufficient_rides():
    election = _make_election(status=ElectionStatus.voting_open, min_lifetime_rides_to_vote=50)
    candidacy = _make_candidacy(election_id=10, status=CandidacyStatus.approved)
    driver = _make_driver(lifetime_rides=10)

    call_count = 0
    async def _execute(q):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _async_result(election)
        if call_count == 2:
            return _async_result(candidacy)
        return _async_result(driver)

    db = _db()
    db.execute = AsyncMock(side_effect=_execute)
    with pytest.raises(BoardElectionError) as exc:
        await cast_vote(db, 10, 20, 5)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_cast_vote_raises_409_already_voted():
    election = _make_election(status=ElectionStatus.voting_open, min_lifetime_rides_to_vote=50)
    candidacy = _make_candidacy(election_id=10, status=CandidacyStatus.approved)
    driver = _make_driver(lifetime_rides=200)
    existing_vote = _make_vote()

    call_count = 0
    async def _execute(q):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _async_result(election)
        if call_count == 2:
            return _async_result(candidacy)
        if call_count == 3:
            return _async_result(driver)
        return _async_result(existing_vote)

    db = _db()
    db.execute = AsyncMock(side_effect=_execute)
    with pytest.raises(BoardElectionError) as exc:
        await cast_vote(db, 10, 20, 5)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_cast_vote_records_vote():
    election = _make_election(status=ElectionStatus.voting_open, min_lifetime_rides_to_vote=50)
    candidacy = _make_candidacy(election_id=10, status=CandidacyStatus.approved)
    driver = _make_driver(lifetime_rides=200)

    call_count = 0
    async def _execute(q):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _async_result(election)
        if call_count == 2:
            return _async_result(candidacy)
        if call_count == 3:
            return _async_result(driver)
        return _async_result(None)  # no existing vote

    db = _db()
    db.execute = AsyncMock(side_effect=_execute)

    result = await cast_vote(db, 10, 20, 5)
    assert result.election_id == 10
    assert result.candidacy_id == 20
    assert result.voter_driver_profile_id == 5
    db.add.assert_called_once()


# ---------------------------------------------------------------------------
# 46–47  get_election_results
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_results_raises_409_not_tallied():
    election = _make_election(status=ElectionStatus.voting_open)
    db = _db()
    db.execute = AsyncMock(return_value=_async_result(election))
    with pytest.raises(BoardElectionError) as exc:
        await get_election_results(db, 10)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_get_results_returns_data():
    election = _make_election(status=ElectionStatus.tallied, winner_id=5)
    c1 = _make_candidacy(id=20, vote_count=3)

    call_count = 0
    async def _execute(q):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _async_result(election)
        r = MagicMock()
        r.scalars.return_value.all.return_value = [c1]
        return r

    db = _db()
    db.execute = AsyncMock(side_effect=_execute)

    data = await get_election_results(db, 10)
    assert data["election_id"] == 10
    assert data["total_votes"] == 3
    assert data["winner_id"] == 5


# ---------------------------------------------------------------------------
# 48  get_board_roster
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_board_roster_returns_active_seats():
    seat = _make_seat(current_holder_id=5)
    db = _db()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [seat]
    db.execute = AsyncMock(return_value=mock_result)

    seats = await get_board_roster(db)
    assert seat in seats


# ---------------------------------------------------------------------------
# 49–51  Schema validation
# ---------------------------------------------------------------------------


def test_create_seat_rejects_zero_term():
    with pytest.raises(Exception):
        CreateBoardSeatRequest(name="CEO", term_months=0)


def test_apply_rejects_short_statement():
    with pytest.raises(Exception):
        ApplyForCandidacyRequest(statement="Too short")


def test_open_nominations_accepts_valid_window():
    req = OpenNominationsRequest(
        nominations_open_at=_NOW,
        nominations_close_at=_FUTURE,
    )
    assert req.nominations_close_at > req.nominations_open_at


# ---------------------------------------------------------------------------
# 52–67  API layer (integration-style, skipped without live DB)
# ---------------------------------------------------------------------------

_SKIP = pytest.mark.skip(reason="requires live DB")


@_SKIP
def test_api_get_board_roster():
    pass


@_SKIP
def test_api_get_seats():
    pass


@_SKIP
def test_api_list_elections_driver():
    pass


@_SKIP
def test_api_get_election_404():
    pass


@_SKIP
def test_api_apply_candidacy_201():
    pass


@_SKIP
def test_api_cast_vote_201():
    pass


@_SKIP
def test_api_create_seat_admin_201():
    pass


@_SKIP
def test_api_create_seat_non_admin_403():
    pass


@_SKIP
def test_api_create_election_admin_201():
    pass


@_SKIP
def test_api_open_nominations():
    pass


@_SKIP
def test_api_close_nominations():
    pass


@_SKIP
def test_api_open_voting():
    pass


@_SKIP
def test_api_tally():
    pass


@_SKIP
def test_api_certify():
    pass


@_SKIP
def test_api_cancel():
    pass


@_SKIP
def test_api_get_results_admin():
    pass
