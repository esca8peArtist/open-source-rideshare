"""API endpoints for the user blocklist feature.

Riders and drivers can each block specific counterparties to prevent future
matching. The block is unidirectional (caller → target) but the matching
engine checks both directions, so either party can sever contact.

Rider/Driver endpoints:
  GET    /users/me/blocklist                    — list whom I've blocked (paginated)
  POST   /users/me/blocklist                    — block a user
  DELETE /users/me/blocklist/{blocked_user_id}  — unblock a user

Admin endpoints:
  GET /admin/blocklist                          — all block pairs (paginated)
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.db.database import get_db
from app.models.user import User
from app.schemas.blocklist import (
    AdminBlocklistEntryResponse,
    BlocklistEntryResponse,
    BlockUserRequest,
)
from app.services.blocklist import (
    DEFAULT_PAGE_SIZE,
    block_user,
    get_block_entry,
    list_all_blocks,
    list_blocklist,
    unblock_user,
)

router = APIRouter(tags=["blocklist"])


# ---- User (rider / driver) endpoints ----

@router.get(
    "/users/me/blocklist",
    response_model=list[BlocklistEntryResponse],
    summary="List users I have blocked",
)
async def get_my_blocklist(
    offset: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    entries = await list_blocklist(user.id, db, offset=offset, limit=limit)
    return [
        BlocklistEntryResponse(
            id=e.id,
            blocked_user_id=e.blocked_id,
            reason=e.reason,
            created_at=e.created_at,
        )
        for e in entries
    ]


@router.post(
    "/users/me/blocklist",
    response_model=BlocklistEntryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Block a user",
)
async def block_a_user(
    req: BlockUserRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        entry = await block_user(
            blocker_id=user.id,
            blocked_user_id=req.blocked_user_id,
            db=db,
            reason=req.reason,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    await db.commit()
    await db.refresh(entry)
    return BlocklistEntryResponse(
        id=entry.id,
        blocked_user_id=entry.blocked_id,
        reason=entry.reason,
        created_at=entry.created_at,
    )


@router.delete(
    "/users/me/blocklist/{blocked_user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unblock a user",
)
async def unblock_a_user(
    blocked_user_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    deleted = await unblock_user(user.id, blocked_user_id, db)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Block not found")
    await db.commit()


# ---- Admin endpoints ----

@router.get(
    "/admin/blocklist",
    response_model=list[AdminBlocklistEntryResponse],
    summary="Admin: list all block pairs",
)
async def admin_list_all_blocks(
    offset: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=100),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    entries = await list_all_blocks(db, offset=offset, limit=limit)
    return [
        AdminBlocklistEntryResponse(
            id=e.id,
            blocker_id=e.blocker_id,
            blocked_id=e.blocked_id,
            reason=e.reason,
            created_at=e.created_at,
        )
        for e in entries
    ]
