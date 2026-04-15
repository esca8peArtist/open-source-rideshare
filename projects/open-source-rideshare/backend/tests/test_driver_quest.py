"""Unit tests for driver bonus / quest programs feature.

Tests cover:
- Schema: CreateQuestRequest, UpdateQuestRequest, QuestResponse,
          QuestProgressResponse, ClaimQuestResponse, QuestStatsResponse,
          QuestLeaderboardEntry, QuestLeaderboardResponse
- Service: create_quest, list_active_quests, get_driver_quest_progress,
           list_driver_quests, update_quest_progress, claim_quest_bonus,
           expire_stale_quests, get_quest_leaderboard, admin_list_quests,
           deactivate_quest, update_quest, get_quest_stats
- Router: endpoint structure and wiring
- Edge cases: quest not found, driver not found, ineligibility, double-claim
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure all SQLAlchemy models are registered before mapper configuration
# (DriverQuest has a relationship to ServiceArea which must be resolvable).
import app.models  # noqa: F401

from app.models.driver_quest import DriverQuest, DriverQuestProgress, QuestProgressStatus, QuestType
from app.schemas.driver_quest import (
    ClaimQuestResponse,
    CreateQuestRequest,
    QuestLeaderboardEntry,
    QuestLeaderboardResponse,
    QuestProgressResponse,
    QuestResponse,
    QuestStatsResponse,
    UpdateQuestRequest,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
_FUTURE = _NOW + timedelta(days=7)
_PAST = _NOW - timedelta(days=7)


def _make_quest(
    id: int = 1,
    title: str = "Complete 10 rides",
    quest_type: QuestType = QuestType.ride_count,
    target_value: float = 10.0,
    bonus_amount_cents: int = 5000,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    is_active: bool = True,
    min_rating: float | None = None,
    zone_id: int | None = None,
) -> DriverQuest:
    quest = MagicMock(spec=DriverQuest)
    quest.id = id
    quest.title = title
    quest.description = "Test quest description"
    quest.quest_type = quest_type
    quest.target_value = target_value
    quest.bonus_amount_cents = bonus_amount_cents
    quest.start_time = start_time or _PAST
    quest.end_time = end_time or _FUTURE
    quest.is_active = is_active
    quest.min_rating = min_rating
    quest.zone_id = zone_id
    quest.created_at = _NOW
    quest.updated_at = _NOW
    return quest


def _make_progress(
    id: int = 1,
    quest_id: int = 1,
    driver_profile_id: int = 5,
    current_value: float = 0.0,
    status: QuestProgressStatus = QuestProgressStatus.active,
    completed_at: datetime | None = None,
    claimed_at: datetime | None = None,
    bonus_paid_at: datetime | None = None,
) -> DriverQuestProgress:
    prog = MagicMock(spec=DriverQuestProgress)
    prog.id = id
    prog.quest_id = quest_id
    prog.driver_profile_id = driver_profile_id
    prog.current_value = current_value
    prog.status = status
    prog.completed_at = completed_at
    prog.claimed_at = claimed_at
    prog.bonus_paid_at = bonus_paid_at
    prog.created_at = _NOW
    prog.updated_at = _NOW
    return prog


def _make_driver(id: int = 5, rating_avg: float = 4.8):
    from app.models.driver import DriverProfile
    driver = MagicMock(spec=DriverProfile)
    driver.id = id
    driver.rating_avg = rating_avg
    return driver


# ---------------------------------------------------------------------------
# Schema: CreateQuestRequest
# ---------------------------------------------------------------------------


class TestCreateQuestRequest:
    def test_valid_minimal(self):
        req = CreateQuestRequest(
            title="10 rides quest",
            quest_type=QuestType.ride_count,
            target_value=10.0,
            bonus_amount_cents=5000,
            start_time=_PAST,
            end_time=_FUTURE,
        )
        assert req.title == "10 rides quest"
        assert req.quest_type == QuestType.ride_count
        assert req.description is None
        assert req.min_rating is None
        assert req.zone_id is None

    def test_valid_full(self):
        req = CreateQuestRequest(
            title="Earnings challenge",
            description="Earn $200 this week",
            quest_type=QuestType.earnings_target,
            target_value=20000,
            bonus_amount_cents=1500,
            start_time=_PAST,
            end_time=_FUTURE,
            min_rating=4.5,
            zone_id=3,
        )
        assert req.min_rating == 4.5
        assert req.zone_id == 3

    def test_rejects_zero_target(self):
        with pytest.raises(Exception):
            CreateQuestRequest(
                title="Bad quest",
                quest_type=QuestType.ride_count,
                target_value=0,
                bonus_amount_cents=5000,
                start_time=_PAST,
                end_time=_FUTURE,
            )

    def test_rejects_zero_bonus(self):
        with pytest.raises(Exception):
            CreateQuestRequest(
                title="Bad quest",
                quest_type=QuestType.ride_count,
                target_value=10,
                bonus_amount_cents=0,
                start_time=_PAST,
                end_time=_FUTURE,
            )

    def test_rejects_missing_title(self):
        with pytest.raises(Exception):
            CreateQuestRequest(
                quest_type=QuestType.ride_count,
                target_value=10,
                bonus_amount_cents=5000,
                start_time=_PAST,
                end_time=_FUTURE,
            )

    def test_all_quest_types_valid(self):
        for qt in QuestType:
            req = CreateQuestRequest(
                title=f"Quest {qt}",
                quest_type=qt,
                target_value=5.0,
                bonus_amount_cents=1000,
                start_time=_PAST,
                end_time=_FUTURE,
            )
            assert req.quest_type == qt

    def test_min_rating_bounds(self):
        with pytest.raises(Exception):
            CreateQuestRequest(
                title="Bad",
                quest_type=QuestType.ride_count,
                target_value=5,
                bonus_amount_cents=1000,
                start_time=_PAST,
                end_time=_FUTURE,
                min_rating=5.5,  # exceeds max 5.0
            )


# ---------------------------------------------------------------------------
# Schema: UpdateQuestRequest
# ---------------------------------------------------------------------------


class TestUpdateQuestRequest:
    def test_all_optional(self):
        req = UpdateQuestRequest()
        assert req.title is None
        assert req.description is None
        assert req.is_active is None

    def test_set_is_active_false(self):
        req = UpdateQuestRequest(is_active=False)
        assert req.is_active is False

    def test_set_title(self):
        req = UpdateQuestRequest(title="New title")
        assert req.title == "New title"

    def test_target_value_not_in_schema(self):
        # Verifying the schema intentionally omits target_value
        req = UpdateQuestRequest(title="OK")
        assert not hasattr(req, "target_value")


# ---------------------------------------------------------------------------
# Schema: QuestResponse
# ---------------------------------------------------------------------------


class TestQuestResponse:
    def test_from_attributes(self):
        quest = _make_quest()
        resp = QuestResponse.model_validate(quest)
        assert resp.id == quest.id
        assert resp.title == quest.title
        assert resp.quest_type == QuestType.ride_count
        assert resp.bonus_amount_cents == 5000

    def test_nullable_fields(self):
        quest = _make_quest(min_rating=None, zone_id=None)
        resp = QuestResponse.model_validate(quest)
        assert resp.min_rating is None
        assert resp.zone_id is None


# ---------------------------------------------------------------------------
# Schema: QuestProgressResponse
# ---------------------------------------------------------------------------


class TestQuestProgressResponse:
    def test_construction(self):
        resp = QuestProgressResponse(
            quest_id=1,
            quest_title="10 rides",
            quest_type=QuestType.ride_count,
            target_value=10.0,
            bonus_amount_cents=5000,
            start_time=_PAST,
            end_time=_FUTURE,
            current_value=3.0,
            status=QuestProgressStatus.active,
            completed_at=None,
            claimed_at=None,
            progress_id=99,
        )
        assert resp.current_value == 3.0
        assert resp.status == QuestProgressStatus.active
        assert resp.progress_id == 99


# ---------------------------------------------------------------------------
# Schema: ClaimQuestResponse
# ---------------------------------------------------------------------------


class TestClaimQuestResponse:
    def test_construction(self):
        resp = ClaimQuestResponse(
            quest_id=1,
            bonus_amount_cents=5000,
            claimed_at=_NOW,
        )
        assert resp.bonus_amount_cents == 5000
        assert resp.claimed_at == _NOW


# ---------------------------------------------------------------------------
# Schema: QuestStatsResponse
# ---------------------------------------------------------------------------


class TestQuestStatsResponse:
    def test_construction(self):
        quest = _make_quest()
        qr = QuestResponse.model_validate(quest)
        stats = QuestStatsResponse(
            quest=qr,
            enrolled_count=10,
            completed_count=5,
            claimed_count=3,
            total_bonus_paid_cents=15000,
        )
        assert stats.enrolled_count == 10
        assert stats.total_bonus_paid_cents == 15000


# ---------------------------------------------------------------------------
# Schema: Leaderboard
# ---------------------------------------------------------------------------


class TestQuestLeaderboardSchemas:
    def test_leaderboard_entry(self):
        entry = QuestLeaderboardEntry(
            rank=1,
            driver_profile_id=5,
            current_value=9.5,
            status=QuestProgressStatus.active,
        )
        assert entry.rank == 1
        assert entry.driver_profile_id == 5

    def test_leaderboard_response(self):
        entries = [
            QuestLeaderboardEntry(
                rank=i + 1,
                driver_profile_id=i + 1,
                current_value=float(10 - i),
                status=QuestProgressStatus.active,
            )
            for i in range(3)
        ]
        resp = QuestLeaderboardResponse(quest_id=1, entries=entries)
        assert len(resp.entries) == 3
        assert resp.quest_id == 1


# ---------------------------------------------------------------------------
# Service: create_quest
# ---------------------------------------------------------------------------


class TestCreateQuest:
    @pytest.mark.asyncio
    async def test_creates_and_flushes(self):
        from app.services.driver_quest import create_quest

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        req = CreateQuestRequest(
            title="10 rides",
            quest_type=QuestType.ride_count,
            target_value=10.0,
            bonus_amount_cents=5000,
            start_time=_PAST,
            end_time=_FUTURE,
        )
        result = await create_quest(db, req)
        db.add.assert_called_once()
        db.flush.assert_awaited_once()
        assert result.title == "10 rides"
        assert result.is_active is True

    @pytest.mark.asyncio
    async def test_sets_zone_id(self):
        from app.services.driver_quest import create_quest

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        req = CreateQuestRequest(
            title="Zone quest",
            quest_type=QuestType.peak_hours_rides,
            target_value=5.0,
            bonus_amount_cents=2000,
            start_time=_PAST,
            end_time=_FUTURE,
            zone_id=7,
        )
        result = await create_quest(db, req)
        assert result.zone_id == 7

    @pytest.mark.asyncio
    async def test_min_rating_stored(self):
        from app.services.driver_quest import create_quest

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        req = CreateQuestRequest(
            title="High-rated quest",
            quest_type=QuestType.acceptance_rate,
            target_value=90.0,
            bonus_amount_cents=3000,
            start_time=_PAST,
            end_time=_FUTURE,
            min_rating=4.7,
        )
        result = await create_quest(db, req)
        assert result.min_rating == 4.7


# ---------------------------------------------------------------------------
# Service: list_active_quests
# ---------------------------------------------------------------------------


class TestListActiveQuests:
    @pytest.mark.asyncio
    async def test_returns_active_quests(self):
        from app.services.driver_quest import list_active_quests

        db = AsyncMock()
        q1 = _make_quest(id=1)
        q2 = _make_quest(id=2, title="Earnings quest", quest_type=QuestType.earnings_target)
        result = MagicMock()
        result.scalars.return_value.all.return_value = [q1, q2]
        db.execute = AsyncMock(return_value=result)

        quests = await list_active_quests(db)
        assert len(quests) == 2

    @pytest.mark.asyncio
    async def test_returns_empty_when_none(self):
        from app.services.driver_quest import list_active_quests

        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result)

        quests = await list_active_quests(db)
        assert quests == []


# ---------------------------------------------------------------------------
# Service: get_driver_quest_progress
# ---------------------------------------------------------------------------


class TestGetDriverQuestProgress:
    @pytest.mark.asyncio
    async def test_returns_existing(self):
        from app.services.driver_quest import get_driver_quest_progress

        db = AsyncMock()
        prog = _make_progress()
        result = MagicMock()
        result.scalar_one_or_none.return_value = prog
        db.execute = AsyncMock(return_value=result)

        found = await get_driver_quest_progress(db, driver_profile_id=5, quest_id=1)
        assert found is prog

    @pytest.mark.asyncio
    async def test_returns_none_when_missing(self):
        from app.services.driver_quest import get_driver_quest_progress

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)

        found = await get_driver_quest_progress(db, driver_profile_id=5, quest_id=99)
        assert found is None


# ---------------------------------------------------------------------------
# Service: update_quest_progress
# ---------------------------------------------------------------------------


class TestUpdateQuestProgress:
    @pytest.mark.asyncio
    async def test_increments_value(self):
        from app.services.driver_quest import update_quest_progress

        db = AsyncMock()
        prog = _make_progress(current_value=3.0, status=QuestProgressStatus.active)
        quest = _make_quest(target_value=10.0)

        progress_result = MagicMock()
        progress_result.scalar_one_or_none.return_value = prog
        quest_result = MagicMock()
        quest_result.scalar_one_or_none.return_value = quest

        db.execute = AsyncMock(side_effect=[progress_result, quest_result])
        db.flush = AsyncMock()

        result = await update_quest_progress(db, 5, 1, increment=2.0)
        assert float(result.current_value) == 5.0
        assert result.status == QuestProgressStatus.active

    @pytest.mark.asyncio
    async def test_auto_completes_when_target_reached(self):
        from app.services.driver_quest import update_quest_progress

        db = AsyncMock()
        prog = _make_progress(current_value=8.0, status=QuestProgressStatus.active)
        quest = _make_quest(target_value=10.0)

        progress_result = MagicMock()
        progress_result.scalar_one_or_none.return_value = prog
        quest_result = MagicMock()
        quest_result.scalar_one_or_none.return_value = quest

        db.execute = AsyncMock(side_effect=[progress_result, quest_result])
        db.flush = AsyncMock()

        result = await update_quest_progress(db, 5, 1, increment=2.0)
        assert float(result.current_value) == 10.0
        assert result.status == QuestProgressStatus.completed
        assert result.completed_at is not None

    @pytest.mark.asyncio
    async def test_completes_when_value_exceeds_target(self):
        from app.services.driver_quest import update_quest_progress

        db = AsyncMock()
        prog = _make_progress(current_value=9.0, status=QuestProgressStatus.active)
        quest = _make_quest(target_value=10.0)

        progress_result = MagicMock()
        progress_result.scalar_one_or_none.return_value = prog
        quest_result = MagicMock()
        quest_result.scalar_one_or_none.return_value = quest

        db.execute = AsyncMock(side_effect=[progress_result, quest_result])
        db.flush = AsyncMock()

        result = await update_quest_progress(db, 5, 1, increment=5.0)
        # Exceeds target — should still be marked complete
        assert result.status == QuestProgressStatus.completed

    @pytest.mark.asyncio
    async def test_returns_none_if_progress_missing(self):
        from app.services.driver_quest import update_quest_progress

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)

        out = await update_quest_progress(db, 5, 999, increment=1.0)
        assert out is None

    @pytest.mark.asyncio
    async def test_no_op_when_already_completed(self):
        from app.services.driver_quest import update_quest_progress

        db = AsyncMock()
        prog = _make_progress(current_value=10.0, status=QuestProgressStatus.completed)

        progress_result = MagicMock()
        progress_result.scalar_one_or_none.return_value = prog
        db.execute = AsyncMock(return_value=progress_result)

        result = await update_quest_progress(db, 5, 1, increment=5.0)
        # Should return existing record without modification
        assert result.status == QuestProgressStatus.completed

    @pytest.mark.asyncio
    async def test_no_op_when_claimed(self):
        from app.services.driver_quest import update_quest_progress

        db = AsyncMock()
        prog = _make_progress(current_value=10.0, status=QuestProgressStatus.claimed)

        progress_result = MagicMock()
        progress_result.scalar_one_or_none.return_value = prog
        db.execute = AsyncMock(return_value=progress_result)

        result = await update_quest_progress(db, 5, 1, increment=1.0)
        assert result.status == QuestProgressStatus.claimed


# ---------------------------------------------------------------------------
# Service: claim_quest_bonus
# ---------------------------------------------------------------------------


class TestClaimQuestBonus:
    @pytest.mark.asyncio
    async def test_successful_claim(self):
        from app.services.driver_quest import claim_quest_bonus

        db = AsyncMock()
        prog = _make_progress(status=QuestProgressStatus.completed)
        quest = _make_quest(bonus_amount_cents=5000)

        prog_result = MagicMock()
        prog_result.scalar_one_or_none.return_value = prog
        quest_result = MagicMock()
        quest_result.scalar_one_or_none.return_value = quest

        db.execute = AsyncMock(side_effect=[prog_result, quest_result])
        db.flush = AsyncMock()

        result = await claim_quest_bonus(db, driver_profile_id=5, quest_id=1)
        assert result["bonus_amount_cents"] == 5000
        assert result["quest_id"] == 1
        assert result["claimed_at"] is not None
        assert prog.status == QuestProgressStatus.claimed
        assert prog.claimed_at is not None
        assert prog.bonus_paid_at is not None

    @pytest.mark.asyncio
    async def test_raises_if_not_completed(self):
        from app.services.driver_quest import claim_quest_bonus

        db = AsyncMock()
        prog = _make_progress(status=QuestProgressStatus.active)

        prog_result = MagicMock()
        prog_result.scalar_one_or_none.return_value = prog
        db.execute = AsyncMock(return_value=prog_result)

        with pytest.raises(ValueError, match="not yet completed"):
            await claim_quest_bonus(db, 5, 1)

    @pytest.mark.asyncio
    async def test_raises_if_already_claimed(self):
        from app.services.driver_quest import claim_quest_bonus

        db = AsyncMock()
        prog = _make_progress(status=QuestProgressStatus.claimed)

        prog_result = MagicMock()
        prog_result.scalar_one_or_none.return_value = prog
        db.execute = AsyncMock(return_value=prog_result)

        with pytest.raises(ValueError, match="already claimed"):
            await claim_quest_bonus(db, 5, 1)

    @pytest.mark.asyncio
    async def test_raises_if_progress_not_found(self):
        from app.services.driver_quest import claim_quest_bonus

        db = AsyncMock()
        prog_result = MagicMock()
        prog_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=prog_result)

        with pytest.raises(ValueError, match="not found"):
            await claim_quest_bonus(db, 5, 999)

    @pytest.mark.asyncio
    async def test_raises_if_expired(self):
        from app.services.driver_quest import claim_quest_bonus

        db = AsyncMock()
        prog = _make_progress(status=QuestProgressStatus.expired)

        prog_result = MagicMock()
        prog_result.scalar_one_or_none.return_value = prog
        db.execute = AsyncMock(return_value=prog_result)

        with pytest.raises(ValueError):
            await claim_quest_bonus(db, 5, 1)


# ---------------------------------------------------------------------------
# Service: expire_stale_quests
# ---------------------------------------------------------------------------


class TestExpireStaleQuests:
    @pytest.mark.asyncio
    async def test_expires_active_records(self):
        from app.services.driver_quest import expire_stale_quests

        db = AsyncMock()
        expired_quest = _make_quest(id=1, end_time=_PAST - timedelta(days=1))

        prog1 = _make_progress(id=1, quest_id=1, status=QuestProgressStatus.active)
        prog2 = _make_progress(id=2, quest_id=1, status=QuestProgressStatus.completed)

        quests_result = MagicMock()
        quests_result.scalars.return_value.all.return_value = [expired_quest]
        stale_result = MagicMock()
        stale_result.scalars.return_value.all.return_value = [prog1, prog2]

        db.execute = AsyncMock(side_effect=[quests_result, stale_result])
        db.flush = AsyncMock()

        count = await expire_stale_quests(db)
        assert count == 2
        assert prog1.status == QuestProgressStatus.expired
        assert prog2.status == QuestProgressStatus.expired

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_expired_quests(self):
        from app.services.driver_quest import expire_stale_quests

        db = AsyncMock()
        quests_result = MagicMock()
        quests_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=quests_result)

        count = await expire_stale_quests(db)
        assert count == 0

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_stale_progress(self):
        from app.services.driver_quest import expire_stale_quests

        db = AsyncMock()
        expired_quest = _make_quest(id=1, end_time=_PAST)

        quests_result = MagicMock()
        quests_result.scalars.return_value.all.return_value = [expired_quest]
        stale_result = MagicMock()
        stale_result.scalars.return_value.all.return_value = []

        db.execute = AsyncMock(side_effect=[quests_result, stale_result])
        db.flush = AsyncMock()

        count = await expire_stale_quests(db)
        assert count == 0


# ---------------------------------------------------------------------------
# Service: admin_list_quests
# ---------------------------------------------------------------------------


class TestAdminListQuests:
    @pytest.mark.asyncio
    async def test_active_only_by_default(self):
        from app.services.driver_quest import admin_list_quests

        db = AsyncMock()
        q1 = _make_quest(id=1)
        result = MagicMock()
        result.scalars.return_value.all.return_value = [q1]
        db.execute = AsyncMock(return_value=result)

        quests = await admin_list_quests(db, include_inactive=False)
        assert len(quests) == 1

    @pytest.mark.asyncio
    async def test_include_inactive(self):
        from app.services.driver_quest import admin_list_quests

        db = AsyncMock()
        q1 = _make_quest(id=1)
        q2 = _make_quest(id=2, is_active=False)
        result = MagicMock()
        result.scalars.return_value.all.return_value = [q1, q2]
        db.execute = AsyncMock(return_value=result)

        quests = await admin_list_quests(db, include_inactive=True)
        assert len(quests) == 2


# ---------------------------------------------------------------------------
# Service: deactivate_quest
# ---------------------------------------------------------------------------


class TestDeactivateQuest:
    @pytest.mark.asyncio
    async def test_sets_inactive(self):
        from app.services.driver_quest import deactivate_quest

        db = AsyncMock()
        quest = _make_quest(is_active=True)
        result = MagicMock()
        result.scalar_one_or_none.return_value = quest
        db.execute = AsyncMock(return_value=result)
        db.flush = AsyncMock()

        returned = await deactivate_quest(db, quest_id=1)
        assert returned.is_active is False

    @pytest.mark.asyncio
    async def test_returns_none_if_not_found(self):
        from app.services.driver_quest import deactivate_quest

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)

        returned = await deactivate_quest(db, quest_id=999)
        assert returned is None


# ---------------------------------------------------------------------------
# Service: get_quest_leaderboard
# ---------------------------------------------------------------------------


class TestGetQuestLeaderboard:
    @pytest.mark.asyncio
    async def test_returns_top_records(self):
        from app.services.driver_quest import get_quest_leaderboard

        db = AsyncMock()
        records = [_make_progress(id=i, driver_profile_id=i, current_value=float(10 - i)) for i in range(1, 4)]
        result = MagicMock()
        result.scalars.return_value.all.return_value = records
        db.execute = AsyncMock(return_value=result)

        top = await get_quest_leaderboard(db, quest_id=1)
        assert len(top) == 3

    @pytest.mark.asyncio
    async def test_empty_leaderboard(self):
        from app.services.driver_quest import get_quest_leaderboard

        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result)

        top = await get_quest_leaderboard(db, quest_id=999)
        assert top == []


# ---------------------------------------------------------------------------
# Service: get_quest_stats
# ---------------------------------------------------------------------------


class TestGetQuestStats:
    @pytest.mark.asyncio
    async def test_correct_stats(self):
        from app.services.driver_quest import get_quest_stats

        db = AsyncMock()
        quest = _make_quest(bonus_amount_cents=5000)

        def _scalar(val):
            r = MagicMock()
            r.scalar_one.return_value = val
            return r

        quest_result = MagicMock()
        quest_result.scalar_one_or_none.return_value = quest

        db.execute = AsyncMock(side_effect=[
            _scalar(10),   # enrolled_count
            _scalar(5),    # completed_count
            _scalar(3),    # claimed_count
            quest_result,  # quest lookup
        ])

        stats = await get_quest_stats(db, quest_id=1)
        assert stats["enrolled_count"] == 10
        assert stats["completed_count"] == 5
        assert stats["claimed_count"] == 3
        assert stats["total_bonus_paid_cents"] == 3 * 5000

    @pytest.mark.asyncio
    async def test_zero_stats_when_no_progress(self):
        from app.services.driver_quest import get_quest_stats

        db = AsyncMock()
        quest = _make_quest(bonus_amount_cents=2000)

        def _scalar(val):
            r = MagicMock()
            r.scalar_one.return_value = val
            return r

        quest_result = MagicMock()
        quest_result.scalar_one_or_none.return_value = quest

        db.execute = AsyncMock(side_effect=[
            _scalar(0),
            _scalar(0),
            _scalar(0),
            quest_result,
        ])

        stats = await get_quest_stats(db, quest_id=1)
        assert stats["total_bonus_paid_cents"] == 0


# ---------------------------------------------------------------------------
# Service: eligibility (min_rating)
# ---------------------------------------------------------------------------


class TestEligibility:
    @pytest.mark.asyncio
    async def test_driver_below_min_rating_gets_ineligible(self):
        from app.services.driver_quest import _get_or_create_progress

        db = AsyncMock()
        # No existing progress
        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=existing_result)
        db.add = MagicMock()
        db.flush = AsyncMock()

        quest = _make_quest(min_rating=4.5)
        driver = _make_driver(rating_avg=4.0)  # below min_rating

        progress = await _get_or_create_progress(db, driver.id, quest.id, quest, driver)
        db.add.assert_called_once()
        assert progress.status == QuestProgressStatus.ineligible

    @pytest.mark.asyncio
    async def test_driver_meeting_min_rating_gets_active(self):
        from app.services.driver_quest import _get_or_create_progress

        db = AsyncMock()
        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=existing_result)
        db.add = MagicMock()
        db.flush = AsyncMock()

        quest = _make_quest(min_rating=4.5)
        driver = _make_driver(rating_avg=4.8)  # above min_rating

        progress = await _get_or_create_progress(db, driver.id, quest.id, quest, driver)
        assert progress.status == QuestProgressStatus.active

    @pytest.mark.asyncio
    async def test_no_min_rating_always_eligible(self):
        from app.services.driver_quest import _get_or_create_progress

        db = AsyncMock()
        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=existing_result)
        db.add = MagicMock()
        db.flush = AsyncMock()

        quest = _make_quest(min_rating=None)
        driver = _make_driver(rating_avg=2.0)  # low but no restriction

        progress = await _get_or_create_progress(db, driver.id, quest.id, quest, driver)
        assert progress.status == QuestProgressStatus.active


# ---------------------------------------------------------------------------
# Router: structure
# ---------------------------------------------------------------------------


class TestRouterStructure:
    def test_router_has_expected_driver_routes(self):
        from app.api.v1.driver_quest import router

        paths = {route.path for route in router.routes}
        assert "/drivers/me/quests" in paths
        assert "/drivers/me/quests/{quest_id}" in paths
        assert "/drivers/me/quests/{quest_id}/claim" in paths

    def test_router_has_expected_admin_routes(self):
        from app.api.v1.driver_quest import router

        paths = {route.path for route in router.routes}
        assert "/admin/quests" in paths
        assert "/admin/quests/{quest_id}" in paths
        assert "/admin/quests/{quest_id}/leaderboard" in paths

    def test_router_tag(self):
        from app.api.v1.driver_quest import router

        assert "driver-quests" in router.tags

    def test_list_quests_is_get(self):
        from app.api.v1.driver_quest import router

        routes = [
            r for r in router.routes
            if hasattr(r, "methods") and "GET" in r.methods
            and r.path == "/drivers/me/quests"
        ]
        assert len(routes) == 1

    def test_claim_quest_is_post(self):
        from app.api.v1.driver_quest import router

        routes = [
            r for r in router.routes
            if hasattr(r, "methods") and "POST" in r.methods
            and r.path == "/drivers/me/quests/{quest_id}/claim"
        ]
        assert len(routes) == 1

    def test_admin_create_is_post(self):
        from app.api.v1.driver_quest import router

        routes = [
            r for r in router.routes
            if hasattr(r, "methods") and "POST" in r.methods
            and r.path == "/admin/quests"
        ]
        assert len(routes) == 1

    def test_admin_update_is_put(self):
        from app.api.v1.driver_quest import router

        routes = [
            r for r in router.routes
            if hasattr(r, "methods") and "PUT" in r.methods
            and r.path == "/admin/quests/{quest_id}"
        ]
        assert len(routes) == 1

    def test_leaderboard_is_get(self):
        from app.api.v1.driver_quest import router

        routes = [
            r for r in router.routes
            if hasattr(r, "methods") and "GET" in r.methods
            and r.path == "/admin/quests/{quest_id}/leaderboard"
        ]
        assert len(routes) == 1


# ---------------------------------------------------------------------------
# Router: service function signatures
# ---------------------------------------------------------------------------


class TestServiceFunctionSignatures:
    def test_create_quest_signature(self):
        import inspect
        from app.services.driver_quest import create_quest

        sig = inspect.signature(create_quest)
        params = list(sig.parameters.keys())
        assert "db" in params
        assert "quest_data" in params

    def test_update_quest_progress_signature(self):
        import inspect
        from app.services.driver_quest import update_quest_progress

        sig = inspect.signature(update_quest_progress)
        params = list(sig.parameters.keys())
        assert "db" in params
        assert "driver_profile_id" in params
        assert "quest_id" in params
        assert "increment" in params

    def test_claim_quest_bonus_signature(self):
        import inspect
        from app.services.driver_quest import claim_quest_bonus

        sig = inspect.signature(claim_quest_bonus)
        params = list(sig.parameters.keys())
        assert "db" in params
        assert "driver_profile_id" in params
        assert "quest_id" in params

    def test_expire_stale_quests_signature(self):
        import inspect
        from app.services.driver_quest import expire_stale_quests

        sig = inspect.signature(expire_stale_quests)
        params = list(sig.parameters.keys())
        assert "db" in params

    def test_get_quest_leaderboard_signature(self):
        import inspect
        from app.services.driver_quest import get_quest_leaderboard

        sig = inspect.signature(get_quest_leaderboard)
        params = list(sig.parameters.keys())
        assert "db" in params
        assert "quest_id" in params

    def test_admin_list_quests_signature(self):
        import inspect
        from app.services.driver_quest import admin_list_quests

        sig = inspect.signature(admin_list_quests)
        params = list(sig.parameters.keys())
        assert "db" in params
        assert "include_inactive" in params

    def test_deactivate_quest_signature(self):
        import inspect
        from app.services.driver_quest import deactivate_quest

        sig = inspect.signature(deactivate_quest)
        params = list(sig.parameters.keys())
        assert "db" in params
        assert "quest_id" in params


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_list_driver_quests_driver_not_found(self):
        from app.services.driver_quest import list_driver_quests

        db = AsyncMock()
        driver_result = MagicMock()
        driver_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=driver_result)

        result = await list_driver_quests(db, driver_profile_id=999)
        assert result == []

    @pytest.mark.asyncio
    async def test_update_quest_progress_quest_not_found(self):
        from app.services.driver_quest import update_quest_progress

        db = AsyncMock()
        prog = _make_progress(status=QuestProgressStatus.active)

        progress_result = MagicMock()
        progress_result.scalar_one_or_none.return_value = prog
        quest_result = MagicMock()
        quest_result.scalar_one_or_none.return_value = None

        db.execute = AsyncMock(side_effect=[progress_result, quest_result])

        result = await update_quest_progress(db, 5, 999, increment=1.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_deactivate_already_inactive(self):
        from app.services.driver_quest import deactivate_quest

        db = AsyncMock()
        quest = _make_quest(is_active=False)
        result = MagicMock()
        result.scalar_one_or_none.return_value = quest
        db.execute = AsyncMock(return_value=result)
        db.flush = AsyncMock()

        # Should still set is_active=False without error
        returned = await deactivate_quest(db, quest_id=1)
        assert returned.is_active is False

    @pytest.mark.asyncio
    async def test_update_quest_not_found(self):
        from app.services.driver_quest import update_quest

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)

        returned = await update_quest(db, quest_id=999, title="New")
        assert returned is None

    @pytest.mark.asyncio
    async def test_update_quest_title(self):
        from app.services.driver_quest import update_quest

        db = AsyncMock()
        quest = _make_quest(title="Old title")
        result = MagicMock()
        result.scalar_one_or_none.return_value = quest
        db.execute = AsyncMock(return_value=result)
        db.flush = AsyncMock()

        returned = await update_quest(db, quest_id=1, title="New title")
        assert returned.title == "New title"
