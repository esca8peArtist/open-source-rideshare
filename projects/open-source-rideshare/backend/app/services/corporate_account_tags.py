"""Service layer for Corporate Account Tags.

Platform admins label corporate accounts with short slugified tags for
internal classification and bulk filtering.  Tags are ad-hoc strings — no
separate registry.  Adding a tag that already exists on an account returns
a 409 Conflict.

Service functions are async and require a SQLAlchemy ``AsyncSession``.

Public surface
--------------
add_tag(db, account_id, tag, created_by_id)           -> TagResponse
remove_tag(db, account_id, tag)                        -> None
list_tags(db, account_id)                              -> list[TagResponse]
get_platform_tag_summary(db, *, skip, limit)           -> TagSummaryListResponse
list_accounts_by_tag(db, tag, *, skip, limit)          -> AccountsByTagResponse
bulk_add_tags(db, account_id, tags, created_by_id)     -> BulkAddResult
"""

from __future__ import annotations

from typing import Optional, Sequence

from fastapi import HTTPException, status
from sqlalchemy import asc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_account_tag import CorporateAccountTag
from app.schemas.corporate_account_tag import (
    AccountsByTagResponse,
    BulkAddResult,
    TagListResponse,
    TagResponse,
    TagSummaryListResponse,
    TagSummaryResponse,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_tag_row(
    db: AsyncSession,
    account_id: int,
    tag: str,
) -> CorporateAccountTag | None:
    """Return the tag row for (account_id, tag), or None."""
    result = await db.execute(
        select(CorporateAccountTag).where(
            CorporateAccountTag.account_id == account_id,
            CorporateAccountTag.tag == tag,
        )
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Add
# ---------------------------------------------------------------------------


async def add_tag(
    db: AsyncSession,
    account_id: int,
    tag: str,
    created_by_id: Optional[int],
) -> TagResponse:
    """Add a tag to a corporate account.

    Args:
        db:             Database session.
        account_id:     Target corporate account.
        tag:            Normalised tag string (caller is responsible for normalisation).
        created_by_id:  User ID of the platform admin adding the tag.

    Returns:
        TagResponse for the newly created tag.

    Raises:
        HTTP 409: When the tag already exists on the account.
    """
    existing = await _get_tag_row(db, account_id, tag)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Tag '{tag}' already exists on this account.",
        )

    row = CorporateAccountTag(
        account_id=account_id,
        tag=tag,
        created_by_id=created_by_id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return TagResponse.model_validate(row)


# ---------------------------------------------------------------------------
# Remove
# ---------------------------------------------------------------------------


async def remove_tag(
    db: AsyncSession,
    account_id: int,
    tag: str,
) -> None:
    """Remove a tag from a corporate account.

    Args:
        db:         Database session.
        account_id: Corporate account to remove the tag from.
        tag:        Normalised tag string.

    Raises:
        HTTP 404: When the tag does not exist on the account.
    """
    row = await _get_tag_row(db, account_id, tag)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tag '{tag}' not found on this account.",
        )
    await db.delete(row)
    await db.commit()


# ---------------------------------------------------------------------------
# List (per account)
# ---------------------------------------------------------------------------


async def list_tags(
    db: AsyncSession,
    account_id: int,
) -> list[TagResponse]:
    """List all tags on a corporate account, sorted alphabetically.

    Args:
        db:         Database session.
        account_id: Corporate account to query.

    Returns:
        List of TagResponse records, sorted by tag string.
    """
    result = await db.execute(
        select(CorporateAccountTag)
        .where(CorporateAccountTag.account_id == account_id)
        .order_by(asc(CorporateAccountTag.tag))
    )
    rows = result.scalars().all()
    return [TagResponse.model_validate(r) for r in rows]


# ---------------------------------------------------------------------------
# Platform-wide tag index
# ---------------------------------------------------------------------------


async def get_platform_tag_summary(
    db: AsyncSession,
    *,
    skip: int = 0,
    limit: int = 100,
) -> TagSummaryListResponse:
    """Return all distinct tags used across all corporate accounts.

    Results are ordered by account_count descending (most-used tags first).

    Args:
        db:    Database session.
        skip:  Pagination offset.
        limit: Maximum entries to return (max 500).

    Returns:
        TagSummaryListResponse with tag + account_count pairs.
    """
    q = (
        select(
            CorporateAccountTag.tag,
            func.count(CorporateAccountTag.account_id.distinct()).label("account_count"),
        )
        .group_by(CorporateAccountTag.tag)
        .order_by(func.count(CorporateAccountTag.account_id.distinct()).desc(), asc(CorporateAccountTag.tag))
        .offset(skip)
        .limit(min(limit, 500))
    )
    result = await db.execute(q)
    rows = result.all()
    summaries = [TagSummaryResponse(tag=r.tag, account_count=r.account_count) for r in rows]
    return TagSummaryListResponse(tags=summaries, total=len(summaries))


# ---------------------------------------------------------------------------
# Accounts by tag
# ---------------------------------------------------------------------------


async def list_accounts_by_tag(
    db: AsyncSession,
    tag: str,
    *,
    skip: int = 0,
    limit: int = 100,
) -> AccountsByTagResponse:
    """Return corporate account IDs that carry a given tag.

    Args:
        db:    Database session.
        tag:   Normalised tag string.
        skip:  Pagination offset.
        limit: Maximum entries to return (max 500).

    Returns:
        AccountsByTagResponse with tag and list of account_ids.
    """
    result = await db.execute(
        select(CorporateAccountTag.account_id)
        .where(CorporateAccountTag.tag == tag)
        .order_by(asc(CorporateAccountTag.account_id))
        .offset(skip)
        .limit(min(limit, 500))
    )
    account_ids = [row[0] for row in result.all()]
    return AccountsByTagResponse(tag=tag, account_ids=account_ids, total=len(account_ids))


# ---------------------------------------------------------------------------
# Bulk add
# ---------------------------------------------------------------------------


async def bulk_add_tags(
    db: AsyncSession,
    account_id: int,
    tags: list[str],
    created_by_id: Optional[int],
) -> BulkAddResult:
    """Add multiple tags to a corporate account in one call.

    Tags that already exist on the account are silently skipped (no 409).
    Duplicate tags in the input list are deduplicated before processing.

    Args:
        db:             Database session.
        account_id:     Target corporate account.
        tags:           List of normalised tag strings.
        created_by_id:  User ID of the platform admin performing the operation.

    Returns:
        BulkAddResult with added, already_existed, and full tag records for new tags.
    """
    unique_tags = list(dict.fromkeys(tags))  # deduplicate preserving order

    # Fetch all existing tags for this account in one query
    result = await db.execute(
        select(CorporateAccountTag.tag).where(
            CorporateAccountTag.account_id == account_id,
            CorporateAccountTag.tag.in_(unique_tags),
        )
    )
    existing_tags = {row[0] for row in result.all()}

    added: list[str] = []
    already_existed: list[str] = []
    new_rows: list[CorporateAccountTag] = []

    for tag in unique_tags:
        if tag in existing_tags:
            already_existed.append(tag)
        else:
            row = CorporateAccountTag(
                account_id=account_id,
                tag=tag,
                created_by_id=created_by_id,
            )
            db.add(row)
            new_rows.append(row)
            added.append(tag)

    if new_rows:
        await db.commit()
        for row in new_rows:
            await db.refresh(row)

    return BulkAddResult(
        added=added,
        already_existed=already_existed,
        tags=[TagResponse.model_validate(r) for r in new_rows],
    )
