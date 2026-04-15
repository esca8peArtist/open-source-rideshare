"""Driver bonus and quest programs service layer.

Business rules:
- A driver is eligible for a quest if the quest is active, within its time
  window, and (if min_rating is set) their rating_avg >= min_rating.
- Progress is created lazily on first access; if a driver is ineligible the
  record is created with status=ineligible so the front-end can surface it.
- Calling update_quest_progress auto-completes the quest when current_value
  reaches target_value.
- Claiming is idempotent against double-click but raises an error if the
  quest is not yet completed or already claimed.
- expire_stale_quests is intended to be called by a background scheduler.
"""

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver import DriverProfile
from app.models.driver_quest import (
    DriverQuest,
    DriverQuestProgress,
    QuestProgressStatus,
)
from app.schemas.driver_quest import CreateQuestRequest


# ---------------------------------------------------------------------------
# Admin operations
# ---------------------------------------------------------------------------


async def create_quest(db: AsyncSession, quest_data: CreateQuestRequest) -> DriverQuest:
    """Create a new bonus quest."""
    quest = DriverQuest(
        title=quest_data.title,
        description=quest_data.description,
        quest_type=quest_data.quest_type,
        target_value=quest_data.target_value,
        bonus_amount_cents=quest_data.bonus_amount_cents,
        start_time=quest_data.start_time,
        end_time=quest_data.end_time,
        min_rating=quest_data.min_rating,
        zone_id=quest_data.zone_id,
        is_active=True,
    )
    db.add(quest)
    await db.flush()
    return quest


async def admin_list_quests(
    db: AsyncSession,
    include_inactive: bool = False,
) -> list[DriverQuest]:
    """Return all quests; optionally include deactivated ones."""
    stmt = select(DriverQuest).order_by(DriverQuest.start_time.desc())
    if not include_inactive:
        stmt = stmt.where(DriverQuest.is_active.is_(True))
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def deactivate_quest(db: AsyncSession, quest_id: int) -> DriverQuest | None:
    """Set is_active=False on a quest. Returns None if not found."""
    result = await db.execute(select(DriverQuest).where(DriverQuest.id == quest_id))
    quest = result.scalar_one_or_none()
    if quest is None:
        return None
    quest.is_active = False
    await db.flush()
    return quest


async def update_quest(
    db: AsyncSession,
    quest_id: int,
    title: str | None = None,
    description: str | None = None,
    is_active: bool | None = None,
) -> DriverQuest | None:
    """Update mutable quest fields. Returns None if quest not found."""
    result = await db.execute(select(DriverQuest).where(DriverQuest.id == quest_id))
    quest = result.scalar_one_or_none()
    if quest is None:
        return None
    if title is not None:
        quest.title = title
    if description is not None:
        quest.description = description
    if is_active is not None:
        quest.is_active = is_active
    await db.flush()
    return quest


async def get_quest_leaderboard(
    db: AsyncSession,
    quest_id: int,
    limit: int = 20,
) -> list[DriverQuestProgress]:
    """Return top N drivers by current_value for a quest."""
    result = await db.execute(
        select(DriverQuestProgress)
        .where(DriverQuestProgress.quest_id == quest_id)
        .order_by(DriverQuestProgress.current_value.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_quest_stats(db: AsyncSession, quest_id: int) -> dict:
    """Aggregate statistics for admin quest detail view."""
    enrolled_result = await db.execute(
        select(func.count(DriverQuestProgress.id)).where(
            DriverQuestProgress.quest_id == quest_id
        )
    )
    enrolled_count = enrolled_result.scalar_one()

    completed_result = await db.execute(
        select(func.count(DriverQuestProgress.id)).where(
            DriverQuestProgress.quest_id == quest_id,
            DriverQuestProgress.status.in_(
                [QuestProgressStatus.completed, QuestProgressStatus.claimed]
            ),
        )
    )
    completed_count = completed_result.scalar_one()

    claimed_result = await db.execute(
        select(func.count(DriverQuestProgress.id)).where(
            DriverQuestProgress.quest_id == quest_id,
            DriverQuestProgress.status == QuestProgressStatus.claimed,
        )
    )
    claimed_count = claimed_result.scalar_one()

    # Total bonus paid = number of claimed records * bonus_amount_cents
    quest_result = await db.execute(
        select(DriverQuest).where(DriverQuest.id == quest_id)
    )
    quest = quest_result.scalar_one_or_none()
    total_bonus_paid_cents = (
        claimed_count * quest.bonus_amount_cents if quest else 0
    )

    return {
        "enrolled_count": enrolled_count,
        "completed_count": completed_count,
        "claimed_count": claimed_count,
        "total_bonus_paid_cents": total_bonus_paid_cents,
    }


# ---------------------------------------------------------------------------
# Active quest queries
# ---------------------------------------------------------------------------


async def list_active_quests(db: AsyncSession) -> list[DriverQuest]:
    """Return quests currently within their validity window and is_active=True."""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(DriverQuest).where(
            DriverQuest.is_active.is_(True),
            DriverQuest.start_time <= now,
            DriverQuest.end_time >= now,
        ).order_by(DriverQuest.end_time)
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Driver progress operations
# ---------------------------------------------------------------------------


async def get_driver_quest_progress(
    db: AsyncSession,
    driver_profile_id: int,
    quest_id: int,
) -> DriverQuestProgress | None:
    """Fetch existing progress record, or None if it doesn't exist."""
    result = await db.execute(
        select(DriverQuestProgress).where(
            DriverQuestProgress.driver_profile_id == driver_profile_id,
            DriverQuestProgress.quest_id == quest_id,
        )
    )
    return result.scalar_one_or_none()


async def _get_or_create_progress(
    db: AsyncSession,
    driver_profile_id: int,
    quest_id: int,
    quest: DriverQuest,
    driver: DriverProfile,
) -> DriverQuestProgress:
    """Get existing progress or create a new record with eligibility check."""
    existing = await get_driver_quest_progress(db, driver_profile_id, quest_id)
    if existing is not None:
        return existing

    # Eligibility: check min_rating
    now = datetime.now(timezone.utc)
    is_eligible = (
        quest.is_active
        and quest.start_time <= now <= quest.end_time
        and (quest.min_rating is None or driver.rating_avg >= float(quest.min_rating))
    )
    status = QuestProgressStatus.active if is_eligible else QuestProgressStatus.ineligible

    progress = DriverQuestProgress(
        quest_id=quest_id,
        driver_profile_id=driver_profile_id,
        current_value=0,
        status=status,
    )
    db.add(progress)
    await db.flush()
    return progress


async def list_driver_quests(
    db: AsyncSession,
    driver_profile_id: int,
) -> list[dict]:
    """Return all active quests with this driver's progress.

    Creates progress records lazily for quests the driver hasn't interacted
    with yet.
    """
    # Fetch driver profile for eligibility check
    driver_result = await db.execute(
        select(DriverProfile).where(DriverProfile.id == driver_profile_id)
    )
    driver = driver_result.scalar_one_or_none()
    if driver is None:
        return []

    quests = await list_active_quests(db)
    items = []
    for quest in quests:
        progress = await _get_or_create_progress(
            db, driver_profile_id, quest.id, quest, driver
        )
        items.append({"quest": quest, "progress": progress})
    return items


async def update_quest_progress(
    db: AsyncSession,
    driver_profile_id: int,
    quest_id: int,
    increment: float,
) -> DriverQuestProgress | None:
    """Add increment to current_value.

    If current_value reaches or exceeds target_value, status is set to
    completed and completed_at is recorded. Returns None if the progress
    record or quest does not exist.
    """
    progress = await get_driver_quest_progress(db, driver_profile_id, quest_id)
    if progress is None:
        return None

    # Only update if the quest is still in-progress.
    if progress.status not in (QuestProgressStatus.active,):
        return progress

    quest_result = await db.execute(
        select(DriverQuest).where(DriverQuest.id == quest_id)
    )
    quest = quest_result.scalar_one_or_none()
    if quest is None:
        return None

    progress.current_value = float(progress.current_value) + increment

    if float(progress.current_value) >= float(quest.target_value):
        progress.status = QuestProgressStatus.completed
        progress.completed_at = datetime.now(timezone.utc)

    await db.flush()
    return progress


async def claim_quest_bonus(
    db: AsyncSession,
    driver_profile_id: int,
    quest_id: int,
) -> dict:
    """Claim the bonus for a completed quest.

    Returns a dict with quest_id, bonus_amount_cents, and claimed_at.
    Raises ValueError with a user-safe message on invalid state.
    """
    progress = await get_driver_quest_progress(db, driver_profile_id, quest_id)
    if progress is None:
        raise ValueError("Quest progress not found")

    if progress.status == QuestProgressStatus.claimed:
        raise ValueError("Bonus already claimed")

    if progress.status != QuestProgressStatus.completed:
        raise ValueError("Quest is not yet completed")

    quest_result = await db.execute(
        select(DriverQuest).where(DriverQuest.id == quest_id)
    )
    quest = quest_result.scalar_one_or_none()
    if quest is None:
        raise ValueError("Quest not found")

    now = datetime.now(timezone.utc)
    progress.status = QuestProgressStatus.claimed
    progress.claimed_at = now
    progress.bonus_paid_at = now

    await db.flush()

    return {
        "quest_id": quest_id,
        "bonus_amount_cents": quest.bonus_amount_cents,
        "claimed_at": now,
    }


# ---------------------------------------------------------------------------
# Expiry
# ---------------------------------------------------------------------------


async def expire_stale_quests(db: AsyncSession) -> int:
    """Mark active/completed progress records for expired quests as expired.

    Returns the count of records updated.
    """
    now = datetime.now(timezone.utc)

    # Find quests whose end_time has passed.
    expired_quests_result = await db.execute(
        select(DriverQuest).where(
            DriverQuest.end_time < now,
        )
    )
    expired_quests = list(expired_quests_result.scalars().all())
    if not expired_quests:
        return 0

    expired_quest_ids = [q.id for q in expired_quests]

    stale_result = await db.execute(
        select(DriverQuestProgress).where(
            DriverQuestProgress.quest_id.in_(expired_quest_ids),
            DriverQuestProgress.status.in_(
                [QuestProgressStatus.active, QuestProgressStatus.completed]
            ),
        )
    )
    stale_records = list(stale_result.scalars().all())

    for record in stale_records:
        record.status = QuestProgressStatus.expired

    await db.flush()
    return len(stale_records)
