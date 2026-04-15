"""Corporate Account Tags endpoints.

Platform-admin endpoints (require_admin):
  POST   /admin/corporate/accounts/{account_id}/tags          — add a tag
  DELETE /admin/corporate/accounts/{account_id}/tags/{tag}    — remove a tag
  GET    /admin/corporate/accounts/{account_id}/tags          — list tags on account
  POST   /admin/corporate/accounts/{account_id}/tags/bulk     — bulk-add tags
  GET    /admin/corporate/tags                                 — platform tag index
  GET    /admin/corporate/tags/{tag}/accounts                 — accounts with this tag

Member endpoints (authenticated account member):
  GET /corporate/accounts/me/tags — view own account's tags (read-only)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_account_tag import (
    AccountsByTagResponse,
    BulkAddResult,
    TagAdd,
    TagBulkAdd,
    TagListResponse,
    TagResponse,
    TagSummaryListResponse,
    normalise_tag,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_account_tags import (
    add_tag,
    bulk_add_tags,
    get_platform_tag_summary,
    list_accounts_by_tag,
    list_tags,
    remove_tag,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-account-tags"])


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


async def _resolve_member_account(db: AsyncSession, user_id: int) -> int:
    """Return the corporate account ID for the authenticated member.

    Raises HTTP 404 when the user is not a member of any corporate account.
    """
    account = await get_user_account(db, user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return account.id


# ===========================================================================
# Platform-admin endpoints
# ===========================================================================


@router.post(
    "/admin/corporate/accounts/{account_id}/tags",
    response_model=TagResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: add a tag to a corporate account",
)
async def admin_add_tag(
    account_id: int,
    payload: TagAdd,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Add a single tag to a corporate account.

    Tags are normalised automatically: lowercased, spaces/underscores replaced
    with hyphens, non-alphanumeric characters stripped, truncated to 50 chars.

    Returns HTTP 409 when the (normalised) tag already exists on the account.

    Platform admin only.
    """
    return await add_tag(db, account_id=account_id, tag=payload.tag, created_by_id=admin.id)


@router.delete(
    "/admin/corporate/accounts/{account_id}/tags/{tag}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Admin: remove a tag from a corporate account",
)
async def admin_remove_tag(
    account_id: int,
    tag: str,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Remove a tag from a corporate account.

    The ``tag`` path parameter is normalised before lookup, so
    ``/tags/VIP`` and ``/tags/vip`` resolve to the same tag.

    Returns HTTP 404 when the tag does not exist on the account.

    Platform admin only.
    """
    try:
        normalised = normalise_tag(tag)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid tag format.",
        )
    await remove_tag(db, account_id=account_id, tag=normalised)


@router.get(
    "/admin/corporate/accounts/{account_id}/tags",
    response_model=TagListResponse,
    summary="Admin: list tags on a corporate account",
)
async def admin_list_tags(
    account_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all tags on a corporate account, sorted alphabetically.

    Platform admin only.
    """
    tags = await list_tags(db, account_id=account_id)
    return TagListResponse(tags=tags, total=len(tags))


@router.post(
    "/admin/corporate/accounts/{account_id}/tags/bulk",
    response_model=BulkAddResult,
    status_code=status.HTTP_200_OK,
    summary="Admin: bulk-add tags to a corporate account",
)
async def admin_bulk_add_tags(
    account_id: int,
    payload: TagBulkAdd,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Add multiple tags to a corporate account in one request.

    Tags that already exist on the account are silently skipped — no error is
    raised.  The response separates newly ``added`` tags from ``already_existed``
    tags.

    Accepts 1–20 tags per request.  Duplicates within the request are
    deduplicated before processing.

    Platform admin only.
    """
    return await bulk_add_tags(
        db,
        account_id=account_id,
        tags=payload.tags,
        created_by_id=admin.id,
    )


@router.get(
    "/admin/corporate/tags",
    response_model=TagSummaryListResponse,
    summary="Admin: list all tags in use across all corporate accounts",
)
async def admin_platform_tag_index(
    skip: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(100, ge=1, le=500, description="Maximum entries to return"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all distinct tags used across all corporate accounts.

    Each entry includes the tag name and the number of corporate accounts
    that carry it.  Results are ordered by account_count descending
    (most-used tags first), then alphabetically within the same count.

    Platform admin only.
    """
    return await get_platform_tag_summary(db, skip=skip, limit=limit)


@router.get(
    "/admin/corporate/tags/{tag}/accounts",
    response_model=AccountsByTagResponse,
    summary="Admin: list corporate accounts with a specific tag",
)
async def admin_accounts_by_tag(
    tag: str,
    skip: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(100, ge=1, le=500, description="Maximum accounts to return"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return corporate account IDs that carry the specified tag.

    The ``tag`` path parameter is normalised before lookup.

    Platform admin only.
    """
    try:
        normalised = normalise_tag(tag)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid tag format.",
        )
    return await list_accounts_by_tag(db, tag=normalised, skip=skip, limit=limit)


# ===========================================================================
# Member endpoint
# ===========================================================================


@router.get(
    "/corporate/accounts/me/tags",
    response_model=TagListResponse,
    summary="View tags on your corporate account",
)
async def member_list_tags(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the tags applied to the authenticated user's corporate account.

    Tags are visible to all account members (not just admins) so they can see
    how their account is classified on the platform — e.g. plan tier, industry
    vertical.

    Returns HTTP 404 when the user is not a member of any corporate account.
    """
    account_id = await _resolve_member_account(db, user.id)
    tags = await list_tags(db, account_id=account_id)
    return TagListResponse(tags=tags, total=len(tags))
