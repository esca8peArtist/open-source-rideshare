"""Service layer for Corporate Account Hierarchy.

Platform admins manage parent/child relationships between corporate accounts.
Account admins can view their own position in the hierarchy.

Public surface
--------------
create_hierarchy_link(db, data, created_by_id) -> HierarchyLinkResponse
get_hierarchy_link(db, link_id) -> HierarchyLinkResponse
list_children(db, account_id, *, is_active) -> HierarchyLinkListResponse
list_parents(db, account_id, *, is_active) -> HierarchyLinkListResponse
remove_hierarchy_link(db, link_id) -> None
update_hierarchy_link(db, link_id, data) -> HierarchyLinkResponse
get_account_hierarchy_tree(db, account_id) -> HierarchyTreeResponse
get_consolidated_summary(db, account_id) -> ConsolidatedSummaryResponse
list_all_platform(db, *, account_id) -> HierarchyLinkListResponse
"""

from __future__ import annotations

import uuid
from collections import deque
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_account_hierarchy import CorporateAccountHierarchy
from app.schemas.corporate_account_hierarchy import (
    ConsolidatedSummaryResponse,
    HierarchyLinkCreate,
    HierarchyLinkListResponse,
    HierarchyLinkResponse,
    HierarchyLinkUpdate,
    HierarchyTreeNode,
    HierarchyTreeResponse,
)

_MAX_DEPTH = 10


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _link_to_response(link: CorporateAccountHierarchy) -> HierarchyLinkResponse:
    """Convert a CorporateAccountHierarchy ORM instance to a response schema."""
    return HierarchyLinkResponse(
        id=link.id,
        parent_account_id=link.parent_account_id,
        child_account_id=link.child_account_id,
        relationship_type=link.relationship_type,
        notes=link.notes,
        created_by_id=link.created_by_id,
        is_active=link.is_active,
        created_at=link.created_at,
        updated_at=link.updated_at,
    )


async def _get_link_by_id(
    db: AsyncSession, link_id: uuid.UUID
) -> CorporateAccountHierarchy | None:
    """Return the hierarchy link by primary key, or None."""
    result = await db.execute(
        select(CorporateAccountHierarchy).where(
            CorporateAccountHierarchy.id == link_id
        )
    )
    return result.scalar_one_or_none()


async def _get_link_or_404(
    db: AsyncSession, link_id: uuid.UUID
) -> CorporateAccountHierarchy:
    """Return the hierarchy link or raise HTTP 404."""
    link = await _get_link_by_id(db, link_id)
    if link is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hierarchy link not found.",
        )
    return link


async def _get_parent_account_ids(
    db: AsyncSession, account_id: int
) -> list[int]:
    """Return a list of direct parent account_ids for ``account_id``."""
    result = await db.execute(
        select(CorporateAccountHierarchy.parent_account_id).where(
            CorporateAccountHierarchy.child_account_id == account_id,
        )
    )
    return list(result.scalars().all())


async def _get_child_account_ids(
    db: AsyncSession, account_id: int, *, active_only: bool = True
) -> list[int]:
    """Return direct child account_ids for ``account_id`` (active links only by default)."""
    stmt = select(CorporateAccountHierarchy.child_account_id).where(
        CorporateAccountHierarchy.parent_account_id == account_id,
    )
    if active_only:
        stmt = stmt.where(CorporateAccountHierarchy.is_active == True)  # noqa: E712
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _detect_cycle(
    db: AsyncSession, parent_account_id: int, child_account_id: int
) -> bool:
    """Return True if adding parent→child would create a cycle.

    A cycle would occur if ``child_account_id`` already appears anywhere in
    the ancestor chain of ``parent_account_id``.  We walk upward from
    ``parent_account_id`` using BFS with a depth cap of ``_MAX_DEPTH``.
    """
    visited: set[int] = set()
    queue: deque[tuple[int, int]] = deque()
    queue.append((parent_account_id, 0))

    while queue:
        current, depth = queue.popleft()
        if current in visited:
            continue
        visited.add(current)

        if current == child_account_id:
            return True

        if depth >= _MAX_DEPTH:
            continue

        parents = await _get_parent_account_ids(db, current)
        for p in parents:
            if p not in visited:
                queue.append((p, depth + 1))

    return False


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def create_hierarchy_link(
    db: AsyncSession,
    data: HierarchyLinkCreate,
    created_by_id: Optional[int] = None,
) -> HierarchyLinkResponse:
    """Create a new parent→child hierarchy link.

    Raises HTTP 422 if parent_account_id == child_account_id.
    Raises HTTP 409 if a link for this (parent, child) pair already exists.
    Raises HTTP 422 if adding the link would create a cycle.
    """
    if data.parent_account_id == data.child_account_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="parent_account_id and child_account_id must be different.",
        )

    existing = await db.execute(
        select(CorporateAccountHierarchy).where(
            CorporateAccountHierarchy.parent_account_id == data.parent_account_id,
            CorporateAccountHierarchy.child_account_id == data.child_account_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A hierarchy link for this parent/child pair already exists.",
        )

    if await _detect_cycle(db, data.parent_account_id, data.child_account_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Adding this link would create a cycle in the account hierarchy.",
        )

    link = CorporateAccountHierarchy(
        parent_account_id=data.parent_account_id,
        child_account_id=data.child_account_id,
        relationship_type=data.relationship_type,
        notes=data.notes,
        created_by_id=created_by_id,
        is_active=data.is_active,
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)
    return _link_to_response(link)


async def get_hierarchy_link(
    db: AsyncSession, link_id: uuid.UUID
) -> HierarchyLinkResponse:
    """Return a hierarchy link by ID.

    Raises HTTP 404 if not found.
    """
    link = await _get_link_or_404(db, link_id)
    return _link_to_response(link)


async def list_children(
    db: AsyncSession,
    account_id: int,
    *,
    is_active: Optional[bool] = None,
) -> HierarchyLinkListResponse:
    """List all child links for ``account_id``, sorted by child_account_id.

    Optional filter:
      - ``is_active``: True → active only; False → inactive only.
    """
    stmt = select(CorporateAccountHierarchy).where(
        CorporateAccountHierarchy.parent_account_id == account_id,
    )
    if is_active is not None:
        stmt = stmt.where(CorporateAccountHierarchy.is_active == is_active)
    stmt = stmt.order_by(CorporateAccountHierarchy.child_account_id)

    result = await db.execute(stmt)
    links = result.scalars().all()
    return HierarchyLinkListResponse(
        items=[_link_to_response(lnk) for lnk in links],
        total=len(links),
    )


async def list_parents(
    db: AsyncSession,
    account_id: int,
    *,
    is_active: Optional[bool] = None,
) -> HierarchyLinkListResponse:
    """List all parent links for ``account_id``, sorted by parent_account_id.

    Optional filter:
      - ``is_active``: True → active only; False → inactive only.
    """
    stmt = select(CorporateAccountHierarchy).where(
        CorporateAccountHierarchy.child_account_id == account_id,
    )
    if is_active is not None:
        stmt = stmt.where(CorporateAccountHierarchy.is_active == is_active)
    stmt = stmt.order_by(CorporateAccountHierarchy.parent_account_id)

    result = await db.execute(stmt)
    links = result.scalars().all()
    return HierarchyLinkListResponse(
        items=[_link_to_response(lnk) for lnk in links],
        total=len(links),
    )


async def remove_hierarchy_link(
    db: AsyncSession, link_id: uuid.UUID
) -> None:
    """Hard-delete a hierarchy link.

    Raises HTTP 404 if not found.
    """
    link = await _get_link_or_404(db, link_id)
    await db.delete(link)
    await db.commit()


async def update_hierarchy_link(
    db: AsyncSession,
    link_id: uuid.UUID,
    data: HierarchyLinkUpdate,
) -> HierarchyLinkResponse:
    """Partially update a hierarchy link.

    Raises HTTP 404 if not found.
    """
    link = await _get_link_or_404(db, link_id)

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(link, field, value)

    await db.commit()
    await db.refresh(link)
    return _link_to_response(link)


async def get_account_hierarchy_tree(
    db: AsyncSession, account_id: int
) -> HierarchyTreeResponse:
    """Return the full hierarchy tree rooted at ``account_id``.

    Performs BFS downward, following only active child links.  Maximum depth
    is ``_MAX_DEPTH`` to prevent runaway recursion on circular data.
    """

    async def _build_node(
        acc_id: int,
        rel_type=None,
        lnk_id=None,
        depth: int = 0,
    ) -> HierarchyTreeNode:
        node = HierarchyTreeNode(
            account_id=acc_id,
            relationship_type=rel_type,
            link_id=lnk_id,
            children=[],
        )
        if depth >= _MAX_DEPTH:
            return node

        stmt = select(CorporateAccountHierarchy).where(
            CorporateAccountHierarchy.parent_account_id == acc_id,
            CorporateAccountHierarchy.is_active == True,  # noqa: E712
        ).order_by(CorporateAccountHierarchy.child_account_id)
        result = await db.execute(stmt)
        child_links = result.scalars().all()

        for child_link in child_links:
            child_node = await _build_node(
                child_link.child_account_id,
                rel_type=child_link.relationship_type,
                lnk_id=child_link.id,
                depth=depth + 1,
            )
            node.children.append(child_node)

        return node

    root_node = await _build_node(account_id)
    return HierarchyTreeResponse(root_account_id=account_id, tree=root_node)


async def get_consolidated_summary(
    db: AsyncSession, account_id: int
) -> ConsolidatedSummaryResponse:
    """Return aggregate counts for the hierarchy rooted at ``account_id``.

    BFS downward following active links only.  Maximum depth is ``_MAX_DEPTH``.
    """
    all_ids: list[int] = [account_id]
    direct_children_count = 0
    visited: set[int] = {account_id}

    queue: deque[tuple[int, int]] = deque()
    queue.append((account_id, 0))

    while queue:
        current, depth = queue.popleft()
        if depth >= _MAX_DEPTH:
            continue

        stmt = select(CorporateAccountHierarchy.child_account_id).where(
            CorporateAccountHierarchy.parent_account_id == current,
            CorporateAccountHierarchy.is_active == True,  # noqa: E712
        )
        result = await db.execute(stmt)
        children = result.scalars().all()

        for child_id in children:
            if depth == 0:
                direct_children_count += 1
            if child_id not in visited:
                visited.add(child_id)
                all_ids.append(child_id)
                queue.append((child_id, depth + 1))

    all_descendants = len(all_ids) - 1  # exclude root

    return ConsolidatedSummaryResponse(
        root_account_id=account_id,
        total_accounts=len(all_ids),
        direct_children=direct_children_count,
        all_descendants=all_descendants,
        account_ids=all_ids,
    )


async def list_all_platform(
    db: AsyncSession,
    *,
    account_id: Optional[int] = None,
) -> HierarchyLinkListResponse:
    """Platform-admin: list all hierarchy links, optionally filtered by account.

    When ``account_id`` is provided, returns links where that account is either
    the parent OR the child.
    """
    stmt = select(CorporateAccountHierarchy)
    if account_id is not None:
        stmt = stmt.where(
            (CorporateAccountHierarchy.parent_account_id == account_id)
            | (CorporateAccountHierarchy.child_account_id == account_id)
        )
    stmt = stmt.order_by(
        CorporateAccountHierarchy.parent_account_id,
        CorporateAccountHierarchy.child_account_id,
    )
    result = await db.execute(stmt)
    links = result.scalars().all()
    return HierarchyLinkListResponse(
        items=[_link_to_response(lnk) for lnk in links],
        total=len(links),
    )
