"""Driver bonus and quest programs endpoints.

Driver endpoints (require DRIVER role):
  GET  /drivers/me/quests
      List all active quests with the driver's progress. Creates progress
      records on first access.

  GET  /drivers/me/quests/{quest_id}
      Single quest progress detail for the authenticated driver.

  POST /drivers/me/quests/{quest_id}/claim
      Claim the bonus for a completed quest. Returns bonus_amount_cents.
      HTTP 400 if the quest is not completed or already claimed.

Admin endpoints (require ADMIN role):
  GET  /admin/quests
      List all quests. Query param: include_inactive=false (default).

  POST /admin/quests
      Create a new quest.

  GET  /admin/quests/{quest_id}
      Quest detail plus aggregate statistics.

  PUT  /admin/quests/{quest_id}
      Update title / description / is_active only.

  GET  /admin/quests/{quest_id}/leaderboard
      Top 20 drivers by current_value.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin, require_driver
from app.db.database import get_db
from app.models.driver import DriverProfile
from app.models.driver_quest import DriverQuest
from app.models.user import User
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
from app.services.driver_quest import (
    admin_list_quests,
    claim_quest_bonus,
    create_quest,
    deactivate_quest,
    get_driver_quest_progress,
    get_quest_leaderboard,
    get_quest_stats,
    list_driver_quests,
    update_quest,
)

router = APIRouter(tags=["driver-quests"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_driver_profile(user: User, db: AsyncSession) -> DriverProfile:
    result = await db.execute(
        select(DriverProfile).where(DriverProfile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Driver profile not found")
    return profile


async def _get_quest_or_404(quest_id: int, db: AsyncSession) -> DriverQuest:
    result = await db.execute(select(DriverQuest).where(DriverQuest.id == quest_id))
    quest = result.scalar_one_or_none()
    if not quest:
        raise HTTPException(status_code=404, detail="Quest not found")
    return quest


def _progress_response(quest: DriverQuest, progress) -> QuestProgressResponse:
    return QuestProgressResponse(
        quest_id=quest.id,
        quest_title=quest.title,
        quest_type=quest.quest_type,
        target_value=float(quest.target_value),
        bonus_amount_cents=quest.bonus_amount_cents,
        start_time=quest.start_time,
        end_time=quest.end_time,
        current_value=float(progress.current_value),
        status=progress.status,
        completed_at=progress.completed_at,
        claimed_at=progress.claimed_at,
        progress_id=progress.id,
    )


# ---------------------------------------------------------------------------
# Driver: list quests with progress
# ---------------------------------------------------------------------------


@router.get(
    "/drivers/me/quests",
    response_model=list[QuestProgressResponse],
    summary="List active quests with my progress",
)
async def list_my_quests(
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Return all currently active quests along with this driver's progress.
    Progress records are created on first access; ineligible quests are
    included with status=ineligible so the UI can surface them."""
    profile = await _get_driver_profile(user, db)
    items = await list_driver_quests(db, profile.id)
    await db.commit()

    return [
        _progress_response(item["quest"], item["progress"])
        for item in items
    ]


# ---------------------------------------------------------------------------
# Driver: single quest progress
# ---------------------------------------------------------------------------


@router.get(
    "/drivers/me/quests/{quest_id}",
    response_model=QuestProgressResponse,
    summary="Get my progress for a single quest",
)
async def get_my_quest_progress(
    quest_id: int,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Return this driver's progress detail for a specific quest."""
    profile = await _get_driver_profile(user, db)
    quest = await _get_quest_or_404(quest_id, db)
    progress = await get_driver_quest_progress(db, profile.id, quest_id)
    if not progress:
        raise HTTPException(
            status_code=404,
            detail="No progress record found for this quest",
        )
    return _progress_response(quest, progress)


# ---------------------------------------------------------------------------
# Driver: claim bonus
# ---------------------------------------------------------------------------


@router.post(
    "/drivers/me/quests/{quest_id}/claim",
    response_model=ClaimQuestResponse,
    summary="Claim the bonus for a completed quest",
)
async def claim_quest(
    quest_id: int,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Claim the payout for a quest the driver has completed.
    Returns HTTP 400 if the quest is not yet completed or was already claimed."""
    profile = await _get_driver_profile(user, db)
    try:
        result = await claim_quest_bonus(db, profile.id, quest_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await db.commit()
    return ClaimQuestResponse(**result)


# ---------------------------------------------------------------------------
# Admin: list quests
# ---------------------------------------------------------------------------


@router.get(
    "/admin/quests",
    response_model=list[QuestResponse],
    summary="List all quests (admin)",
)
async def admin_list(
    include_inactive: bool = Query(default=False),
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all quests. Pass include_inactive=true to include deactivated quests."""
    quests = await admin_list_quests(db, include_inactive=include_inactive)
    return [QuestResponse.model_validate(q) for q in quests]


# ---------------------------------------------------------------------------
# Admin: create quest
# ---------------------------------------------------------------------------


@router.post(
    "/admin/quests",
    response_model=QuestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new quest (admin)",
)
async def admin_create_quest(
    req: CreateQuestRequest,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new driver bonus quest."""
    if req.end_time <= req.start_time:
        raise HTTPException(
            status_code=400, detail="end_time must be after start_time"
        )
    quest = await create_quest(db, req)
    await db.commit()
    await db.refresh(quest)
    return QuestResponse.model_validate(quest)


# ---------------------------------------------------------------------------
# Admin: quest detail + stats
# ---------------------------------------------------------------------------


@router.get(
    "/admin/quests/{quest_id}",
    response_model=QuestStatsResponse,
    summary="Quest detail with aggregate statistics (admin)",
)
async def admin_quest_detail(
    quest_id: int,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return quest detail and enrollment/completion/claimed statistics."""
    quest = await _get_quest_or_404(quest_id, db)
    stats = await get_quest_stats(db, quest_id)
    return QuestStatsResponse(
        quest=QuestResponse.model_validate(quest),
        **stats,
    )


# ---------------------------------------------------------------------------
# Admin: update quest
# ---------------------------------------------------------------------------


@router.put(
    "/admin/quests/{quest_id}",
    response_model=QuestResponse,
    summary="Update quest title / description / is_active (admin)",
)
async def admin_update_quest(
    quest_id: int,
    req: UpdateQuestRequest,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update mutable quest fields. target_value and bonus_amount_cents cannot
    be changed after creation to protect drivers already in progress."""
    quest = await update_quest(
        db,
        quest_id,
        title=req.title,
        description=req.description,
        is_active=req.is_active,
    )
    if quest is None:
        raise HTTPException(status_code=404, detail="Quest not found")
    await db.commit()
    await db.refresh(quest)
    return QuestResponse.model_validate(quest)


# ---------------------------------------------------------------------------
# Admin: leaderboard
# ---------------------------------------------------------------------------


@router.get(
    "/admin/quests/{quest_id}/leaderboard",
    response_model=QuestLeaderboardResponse,
    summary="Top 20 drivers by progress for a quest (admin)",
)
async def admin_quest_leaderboard(
    quest_id: int,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return the top 20 drivers sorted by current_value descending."""
    await _get_quest_or_404(quest_id, db)
    records = await get_quest_leaderboard(db, quest_id)
    entries = [
        QuestLeaderboardEntry(
            rank=i + 1,
            driver_profile_id=rec.driver_profile_id,
            current_value=float(rec.current_value),
            status=rec.status,
        )
        for i, rec in enumerate(records)
    ]
    return QuestLeaderboardResponse(quest_id=quest_id, entries=entries)
