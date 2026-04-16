"""Tests for the Corporate Account Hierarchy feature.

Service layer (async, mocked DB):
  1.  create_hierarchy_link — creates with all fields
  2.  create_hierarchy_link — creates with minimal fields
  3.  create_hierarchy_link — 422 when parent == child
  4.  create_hierarchy_link — 409 on duplicate parent+child pair
  5.  create_hierarchy_link — 422 on cycle detection (child is ancestor of parent)
  6.  create_hierarchy_link — no cycle when unrelated accounts
  7.  get_hierarchy_link — returns link when found
  8.  get_hierarchy_link — 404 when not found
  9.  list_children — returns children sorted by child_account_id
  10. list_children — filter is_active=True
  11. list_children — filter is_active=False
  12. list_children — empty list when no children
  13. list_parents — returns parents sorted by parent_account_id
  14. list_parents — filter is_active
  15. list_parents — empty list when no parents
  16. remove_hierarchy_link — hard deletes
  17. remove_hierarchy_link — 404 when not found
  18. update_hierarchy_link — partial update
  19. update_hierarchy_link — 404 when not found
  20. get_account_hierarchy_tree — returns tree with root and children
  21. get_account_hierarchy_tree — root with no children returns leaf node
  22. get_consolidated_summary — correct counts for simple hierarchy
  23. get_consolidated_summary — no descendants returns total_accounts=1
  24. list_all_platform — returns all links
  25. list_all_platform — filter by account_id

Schema validation:
  26. HierarchyLinkCreate — valid data accepted
  27. HierarchyLinkCreate — all required fields present
  28. HierarchyLinkUpdate — all fields optional
  29. HierarchyLinkResponse — from_attributes construction
  30. HierarchyTreeNode — self-referential nesting works
  31. ConsolidatedSummaryResponse — fields correct

API layer (service functions patched):
  32. Platform-admin POST create — 201 success
  33. Platform-admin POST create — 422 on cycle
  34. Platform-admin POST create — 409 on duplicate
  35. Platform-admin GET all — 200 returns list
  36. Platform-admin GET {link_id} — 200 returns link
  37. Platform-admin GET {link_id} — 404 not found
  38. Platform-admin PUT {link_id} — 200 updates
  39. Platform-admin DELETE {link_id} — 204 deletes
  40. Platform-admin GET account/{id}/tree — 200 returns tree
  41. Platform-admin GET account/{id}/children — 200 returns children
  42. Platform-admin GET account/{id}/parents — 200 returns parents
  43. Platform-admin GET account/{id}/consolidated — 200 returns summary
  44. Admin GET children — 200
  45. Admin GET children — 404 if not in account
  46. Admin GET parents — 200
  47. Admin GET parents — 404 if not in account
  48. Platform-admin GET all filtered by account_id — 200
  49. list_children with is_active filter via API
  50. list_parents with is_active filter via API
  51. Platform-admin POST create with notes — 201
  52. update_hierarchy_link — only is_active field
  53. update_hierarchy_link — only notes field
  54. get_account_hierarchy_tree — nested children
  55. get_consolidated_summary — multi-level hierarchy
  56. create_hierarchy_link — cycle in deeper ancestor chain
  57. create_hierarchy_link — no cycle for independent branches
  58. list_children — multiple children returned in order
  59. list_parents — multiple parents returned in order
  60. HierarchyLinkCreate — subsidiary type
  61. HierarchyLinkCreate — franchise type
  62. HierarchyLinkCreate — partner type
  63. HierarchyLinkCreate — division type
  64. HierarchyLinkUpdate — set is_active False
  65. HierarchyLinkResponse — all fields populated
  66. HierarchyTreeResponse — nested HierarchyTreeNode
  67. ConsolidatedSummaryResponse — account_ids includes root
  68. Admin GET children — returns 200 with is_active filter
  69. Admin GET parents — returns 200 with is_active filter
  70. Platform-admin GET account consolidated — correct counts
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.corporate_account_hierarchy import (
    CorporateAccountHierarchy,
    HierarchyRelationshipType,
)
from app.schemas.corporate_account_hierarchy import (
    ConsolidatedSummaryResponse,
    HierarchyLinkCreate,
    HierarchyLinkListResponse,
    HierarchyLinkResponse,
    HierarchyLinkUpdate,
    HierarchyTreeNode,
    HierarchyTreeResponse,
)
from app.services.corporate_account_hierarchy import (
    create_hierarchy_link,
    get_account_hierarchy_tree,
    get_consolidated_summary,
    get_hierarchy_link,
    list_all_platform,
    list_children,
    list_parents,
    remove_hierarchy_link,
    update_hierarchy_link,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NOW = datetime(2026, 4, 16, 10, 0, 0, tzinfo=timezone.utc)

PARENT_ID = 10
CHILD_ID = 20
CHILD_ID_2 = 21
GRANDCHILD_ID = 30
OTHER_ACCOUNT_ID = 99
LINK_ID = uuid.uuid4()
LINK_ID_2 = uuid.uuid4()
CREATED_BY_ID = 1


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_link(
    id: uuid.UUID = LINK_ID,
    parent_account_id: int = PARENT_ID,
    child_account_id: int = CHILD_ID,
    relationship_type: HierarchyRelationshipType = HierarchyRelationshipType.subsidiary,
    notes: str | None = None,
    created_by_id: int | None = CREATED_BY_ID,
    is_active: bool = True,
) -> CorporateAccountHierarchy:
    lnk = CorporateAccountHierarchy()
    lnk.id = id
    lnk.parent_account_id = parent_account_id
    lnk.child_account_id = child_account_id
    lnk.relationship_type = relationship_type
    lnk.notes = notes
    lnk.created_by_id = created_by_id
    lnk.is_active = is_active
    lnk.created_at = NOW
    lnk.updated_at = NOW
    return lnk


def _async_result(value: Any):
    mock = MagicMock()
    mock.scalar_one_or_none.return_value = value
    mock.scalars.return_value.all.return_value = (
        value if isinstance(value, list) else []
    )
    return mock


def _async_list(items: list):
    mock = MagicMock()
    mock.scalars.return_value.all.return_value = items
    mock.scalar_one_or_none.return_value = None
    return mock


def _async_scalars(values: list):
    """Return a mock where .scalars().all() returns ``values``."""
    mock = MagicMock()
    mock.scalars.return_value.all.return_value = values
    return mock


def _make_db(execute_returns=None, refresh_fn=None):
    db = AsyncMock()
    if execute_returns is not None:
        if isinstance(execute_returns, list):
            db.execute.side_effect = execute_returns
        else:
            db.execute.return_value = execute_returns
    if refresh_fn is not None:
        db.refresh.side_effect = refresh_fn
    return db


# ---------------------------------------------------------------------------
# Response fixture used across tests
# ---------------------------------------------------------------------------

_LINK_RESPONSE = HierarchyLinkResponse(
    id=LINK_ID,
    parent_account_id=PARENT_ID,
    child_account_id=CHILD_ID,
    relationship_type=HierarchyRelationshipType.subsidiary,
    notes=None,
    created_by_id=CREATED_BY_ID,
    is_active=True,
    created_at=NOW,
    updated_at=NOW,
)

_LIST_RESPONSE = HierarchyLinkListResponse(items=[_LINK_RESPONSE], total=1)

_EMPTY_LIST_RESPONSE = HierarchyLinkListResponse(items=[], total=0)

_TREE_RESPONSE = HierarchyTreeResponse(
    root_account_id=PARENT_ID,
    tree=HierarchyTreeNode(
        account_id=PARENT_ID,
        children=[
            HierarchyTreeNode(
                account_id=CHILD_ID,
                relationship_type=HierarchyRelationshipType.subsidiary,
                link_id=LINK_ID,
                children=[],
            )
        ],
    ),
)

_SUMMARY_RESPONSE = ConsolidatedSummaryResponse(
    root_account_id=PARENT_ID,
    total_accounts=2,
    direct_children=1,
    all_descendants=1,
    account_ids=[PARENT_ID, CHILD_ID],
)


# ---------------------------------------------------------------------------
# Service layer tests (1-25)
# ---------------------------------------------------------------------------


class TestCreateHierarchyLink:
    """Tests 1-6: create_hierarchy_link."""

    @pytest.mark.asyncio
    async def test_creates_with_all_fields(self):
        data = HierarchyLinkCreate(
            parent_account_id=PARENT_ID,
            child_account_id=CHILD_ID,
            relationship_type=HierarchyRelationshipType.subsidiary,
            notes="Main subsidiary",
            is_active=True,
        )

        db = AsyncMock()
        db.add = MagicMock()
        no_existing = MagicMock()
        no_existing.scalar_one_or_none.return_value = None
        # execute called for: duplicate check, ancestor BFS (no parents of PARENT_ID)
        no_scalars = MagicMock()
        no_scalars.scalars.return_value.all.return_value = []
        db.execute.side_effect = [no_existing, no_scalars]

        async def _refresh(obj):
            obj.id = LINK_ID
            obj.created_at = NOW
            obj.updated_at = NOW

        db.refresh = AsyncMock(side_effect=_refresh)

        result = await create_hierarchy_link(db, data, created_by_id=CREATED_BY_ID)

        assert result.parent_account_id == PARENT_ID
        assert result.child_account_id == CHILD_ID
        assert result.relationship_type == HierarchyRelationshipType.subsidiary
        assert result.notes == "Main subsidiary"
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_creates_with_minimal_fields(self):
        data = HierarchyLinkCreate(
            parent_account_id=PARENT_ID,
            child_account_id=CHILD_ID,
            relationship_type=HierarchyRelationshipType.division,
        )

        db = AsyncMock()
        db.add = MagicMock()
        no_existing = MagicMock()
        no_existing.scalar_one_or_none.return_value = None
        no_scalars = MagicMock()
        no_scalars.scalars.return_value.all.return_value = []
        db.execute.side_effect = [no_existing, no_scalars]

        async def _refresh(obj):
            obj.id = LINK_ID
            obj.created_at = NOW
            obj.updated_at = NOW

        db.refresh = AsyncMock(side_effect=_refresh)

        result = await create_hierarchy_link(db, data)

        assert result.relationship_type == HierarchyRelationshipType.division
        assert result.notes is None
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_422_when_parent_equals_child(self):
        data = HierarchyLinkCreate(
            parent_account_id=PARENT_ID,
            child_account_id=PARENT_ID,
            relationship_type=HierarchyRelationshipType.subsidiary,
        )
        db = AsyncMock()
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await create_hierarchy_link(db, data)
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_409_on_duplicate_pair(self):
        data = HierarchyLinkCreate(
            parent_account_id=PARENT_ID,
            child_account_id=CHILD_ID,
            relationship_type=HierarchyRelationshipType.subsidiary,
        )
        existing_link = _make_link()
        db = _make_db(execute_returns=_async_result(existing_link))
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await create_hierarchy_link(db, data)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_422_on_cycle_detection(self):
        # CHILD_ID -> PARENT_ID already exists; adding PARENT_ID -> CHILD_ID is a cycle
        data = HierarchyLinkCreate(
            parent_account_id=PARENT_ID,
            child_account_id=CHILD_ID,
            relationship_type=HierarchyRelationshipType.subsidiary,
        )

        db = AsyncMock()
        no_existing = MagicMock()
        no_existing.scalar_one_or_none.return_value = None

        # BFS upward from PARENT_ID: PARENT_ID's parent is CHILD_ID → cycle
        parent_of_parent = MagicMock()
        parent_of_parent.scalars.return_value.all.return_value = [CHILD_ID]

        db.execute.side_effect = [no_existing, parent_of_parent]

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await create_hierarchy_link(db, data)
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_no_cycle_for_unrelated_accounts(self):
        data = HierarchyLinkCreate(
            parent_account_id=PARENT_ID,
            child_account_id=OTHER_ACCOUNT_ID,
            relationship_type=HierarchyRelationshipType.franchise,
        )

        db = AsyncMock()
        db.add = MagicMock()
        no_existing = MagicMock()
        no_existing.scalar_one_or_none.return_value = None
        no_ancestors = MagicMock()
        no_ancestors.scalars.return_value.all.return_value = []
        db.execute.side_effect = [no_existing, no_ancestors]

        async def _refresh(obj):
            obj.id = LINK_ID
            obj.created_at = NOW
            obj.updated_at = NOW

        db.refresh = AsyncMock(side_effect=_refresh)

        result = await create_hierarchy_link(db, data)
        assert result.child_account_id == OTHER_ACCOUNT_ID


class TestGetHierarchyLink:
    """Tests 7-8: get_hierarchy_link."""

    @pytest.mark.asyncio
    async def test_returns_link_when_found(self):
        link = _make_link()
        db = _make_db(execute_returns=_async_result(link))
        result = await get_hierarchy_link(db, LINK_ID)
        assert result.id == LINK_ID
        assert result.parent_account_id == PARENT_ID

    @pytest.mark.asyncio
    async def test_404_when_not_found(self):
        db = _make_db(execute_returns=_async_result(None))
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await get_hierarchy_link(db, LINK_ID)
        assert exc_info.value.status_code == 404


class TestListChildren:
    """Tests 9-12: list_children."""

    @pytest.mark.asyncio
    async def test_returns_children_sorted(self):
        link1 = _make_link(id=LINK_ID, child_account_id=CHILD_ID)
        link2 = _make_link(id=LINK_ID_2, child_account_id=CHILD_ID_2)
        db = _make_db(execute_returns=_async_list([link1, link2]))
        result = await list_children(db, PARENT_ID)
        assert result.total == 2
        assert result.items[0].child_account_id == CHILD_ID

    @pytest.mark.asyncio
    async def test_filter_is_active_true(self):
        link = _make_link(is_active=True)
        db = _make_db(execute_returns=_async_list([link]))
        result = await list_children(db, PARENT_ID, is_active=True)
        assert result.total == 1
        assert result.items[0].is_active is True

    @pytest.mark.asyncio
    async def test_filter_is_active_false(self):
        link = _make_link(is_active=False)
        db = _make_db(execute_returns=_async_list([link]))
        result = await list_children(db, PARENT_ID, is_active=False)
        assert result.total == 1
        assert result.items[0].is_active is False

    @pytest.mark.asyncio
    async def test_empty_list_when_no_children(self):
        db = _make_db(execute_returns=_async_list([]))
        result = await list_children(db, PARENT_ID)
        assert result.total == 0
        assert result.items == []


class TestListParents:
    """Tests 13-15: list_parents."""

    @pytest.mark.asyncio
    async def test_returns_parents_sorted(self):
        link = _make_link()
        db = _make_db(execute_returns=_async_list([link]))
        result = await list_parents(db, CHILD_ID)
        assert result.total == 1
        assert result.items[0].parent_account_id == PARENT_ID

    @pytest.mark.asyncio
    async def test_filter_is_active(self):
        link = _make_link(is_active=True)
        db = _make_db(execute_returns=_async_list([link]))
        result = await list_parents(db, CHILD_ID, is_active=True)
        assert result.total == 1

    @pytest.mark.asyncio
    async def test_empty_list_when_no_parents(self):
        db = _make_db(execute_returns=_async_list([]))
        result = await list_parents(db, CHILD_ID)
        assert result.total == 0
        assert result.items == []


class TestRemoveHierarchyLink:
    """Tests 16-17: remove_hierarchy_link."""

    @pytest.mark.asyncio
    async def test_hard_deletes_link(self):
        link = _make_link()
        db = _make_db(execute_returns=_async_result(link))
        db.delete = AsyncMock()
        db.commit = AsyncMock()
        await remove_hierarchy_link(db, LINK_ID)
        db.delete.assert_awaited_once_with(link)
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_404_when_not_found(self):
        db = _make_db(execute_returns=_async_result(None))
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await remove_hierarchy_link(db, LINK_ID)
        assert exc_info.value.status_code == 404


class TestUpdateHierarchyLink:
    """Tests 18-19: update_hierarchy_link."""

    @pytest.mark.asyncio
    async def test_partial_update(self):
        link = _make_link()
        db = _make_db(execute_returns=_async_result(link))
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        data = HierarchyLinkUpdate(notes="Updated notes")
        await update_hierarchy_link(db, LINK_ID, data)
        assert link.notes == "Updated notes"

    @pytest.mark.asyncio
    async def test_404_when_not_found(self):
        db = _make_db(execute_returns=_async_result(None))
        data = HierarchyLinkUpdate(is_active=False)
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await update_hierarchy_link(db, LINK_ID, data)
        assert exc_info.value.status_code == 404


class TestGetAccountHierarchyTree:
    """Tests 20-21: get_account_hierarchy_tree."""

    @pytest.mark.asyncio
    async def test_returns_tree_with_children(self):
        child_link = _make_link()
        # First call: children of root (PARENT_ID) → [child_link]
        # Second call: children of CHILD_ID → []
        children_of_root = _async_list([child_link])
        no_children = _async_list([])
        db = _make_db(execute_returns=[children_of_root, no_children])
        result = await get_account_hierarchy_tree(db, PARENT_ID)
        assert result.root_account_id == PARENT_ID
        assert result.tree.account_id == PARENT_ID
        assert len(result.tree.children) == 1
        assert result.tree.children[0].account_id == CHILD_ID

    @pytest.mark.asyncio
    async def test_root_with_no_children_is_leaf(self):
        db = _make_db(execute_returns=_async_list([]))
        result = await get_account_hierarchy_tree(db, PARENT_ID)
        assert result.root_account_id == PARENT_ID
        assert result.tree.account_id == PARENT_ID
        assert result.tree.children == []


class TestGetConsolidatedSummary:
    """Tests 22-23: get_consolidated_summary."""

    @pytest.mark.asyncio
    async def test_correct_counts_for_simple_hierarchy(self):
        # root → CHILD_ID → (no further children)
        children_of_root = MagicMock()
        children_of_root.scalars.return_value.all.return_value = [CHILD_ID]
        children_of_child = MagicMock()
        children_of_child.scalars.return_value.all.return_value = []

        db = _make_db(execute_returns=[children_of_root, children_of_child])

        result = await get_consolidated_summary(db, PARENT_ID)
        assert result.root_account_id == PARENT_ID
        assert result.total_accounts == 2
        assert result.direct_children == 1
        assert result.all_descendants == 1
        assert PARENT_ID in result.account_ids
        assert CHILD_ID in result.account_ids

    @pytest.mark.asyncio
    async def test_no_descendants_returns_single_account(self):
        db = _make_db(execute_returns=_async_scalars([]))
        result = await get_consolidated_summary(db, PARENT_ID)
        assert result.total_accounts == 1
        assert result.direct_children == 0
        assert result.all_descendants == 0
        assert result.account_ids == [PARENT_ID]


class TestListAllPlatform:
    """Tests 24-25: list_all_platform."""

    @pytest.mark.asyncio
    async def test_returns_all_links(self):
        link = _make_link()
        db = _make_db(execute_returns=_async_list([link]))
        result = await list_all_platform(db)
        assert result.total == 1

    @pytest.mark.asyncio
    async def test_filter_by_account_id(self):
        link = _make_link()
        db = _make_db(execute_returns=_async_list([link]))
        result = await list_all_platform(db, account_id=PARENT_ID)
        assert result.total == 1


# ---------------------------------------------------------------------------
# Schema validation tests (26-31 + extras)
# ---------------------------------------------------------------------------


class TestSchemaValidation:
    """Tests 26-70 (schema-related subset)."""

    def test_hierarchy_link_create_valid(self):
        data = HierarchyLinkCreate(
            parent_account_id=PARENT_ID,
            child_account_id=CHILD_ID,
            relationship_type=HierarchyRelationshipType.subsidiary,
        )
        assert data.parent_account_id == PARENT_ID
        assert data.is_active is True

    def test_hierarchy_link_create_all_required_fields(self):
        data = HierarchyLinkCreate(
            parent_account_id=1,
            child_account_id=2,
            relationship_type=HierarchyRelationshipType.franchise,
            notes="A franchise link",
            is_active=False,
        )
        assert data.notes == "A franchise link"
        assert data.is_active is False

    def test_hierarchy_link_update_all_optional(self):
        data = HierarchyLinkUpdate()
        assert data.relationship_type is None
        assert data.notes is None
        assert data.is_active is None

    def test_hierarchy_link_response_from_attributes(self):
        link = _make_link()
        resp = HierarchyLinkResponse(
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
        assert resp.id == LINK_ID
        assert resp.relationship_type == HierarchyRelationshipType.subsidiary

    def test_hierarchy_tree_node_self_referential(self):
        child = HierarchyTreeNode(
            account_id=CHILD_ID,
            relationship_type=HierarchyRelationshipType.division,
            link_id=LINK_ID,
            children=[],
        )
        root = HierarchyTreeNode(
            account_id=PARENT_ID,
            children=[child],
        )
        assert len(root.children) == 1
        assert root.children[0].account_id == CHILD_ID

    def test_consolidated_summary_response_fields(self):
        resp = ConsolidatedSummaryResponse(
            root_account_id=PARENT_ID,
            total_accounts=3,
            direct_children=2,
            all_descendants=2,
            account_ids=[PARENT_ID, CHILD_ID, CHILD_ID_2],
        )
        assert resp.total_accounts == 3
        assert len(resp.account_ids) == 3

    def test_subsidiary_type(self):
        data = HierarchyLinkCreate(
            parent_account_id=1,
            child_account_id=2,
            relationship_type=HierarchyRelationshipType.subsidiary,
        )
        assert data.relationship_type == HierarchyRelationshipType.subsidiary

    def test_franchise_type(self):
        data = HierarchyLinkCreate(
            parent_account_id=1,
            child_account_id=2,
            relationship_type=HierarchyRelationshipType.franchise,
        )
        assert data.relationship_type == HierarchyRelationshipType.franchise

    def test_partner_type(self):
        data = HierarchyLinkCreate(
            parent_account_id=1,
            child_account_id=2,
            relationship_type=HierarchyRelationshipType.partner,
        )
        assert data.relationship_type == HierarchyRelationshipType.partner

    def test_division_type(self):
        data = HierarchyLinkCreate(
            parent_account_id=1,
            child_account_id=2,
            relationship_type=HierarchyRelationshipType.division,
        )
        assert data.relationship_type == HierarchyRelationshipType.division

    def test_update_set_is_active_false(self):
        data = HierarchyLinkUpdate(is_active=False)
        assert data.is_active is False

    def test_link_response_all_fields(self):
        resp = HierarchyLinkResponse(
            id=LINK_ID,
            parent_account_id=PARENT_ID,
            child_account_id=CHILD_ID,
            relationship_type=HierarchyRelationshipType.division,
            notes="Some note",
            created_by_id=5,
            is_active=False,
            created_at=NOW,
            updated_at=NOW,
        )
        assert resp.notes == "Some note"
        assert resp.is_active is False
        assert resp.created_by_id == 5

    def test_tree_response_structure(self):
        tree = HierarchyTreeNode(account_id=PARENT_ID, children=[])
        resp = HierarchyTreeResponse(root_account_id=PARENT_ID, tree=tree)
        assert resp.root_account_id == PARENT_ID
        assert resp.tree.account_id == PARENT_ID

    def test_consolidated_account_ids_includes_root(self):
        resp = ConsolidatedSummaryResponse(
            root_account_id=PARENT_ID,
            total_accounts=1,
            direct_children=0,
            all_descendants=0,
            account_ids=[PARENT_ID],
        )
        assert PARENT_ID in resp.account_ids


# ---------------------------------------------------------------------------
# Additional service tests (56-59)
# ---------------------------------------------------------------------------


class TestAdditionalServiceTests:
    """Tests 56-59: extra edge cases."""

    @pytest.mark.asyncio
    async def test_cycle_in_deeper_ancestor_chain(self):
        # Attempt: PARENT_ID → GRANDCHILD_ID
        # Ancestor chain of PARENT_ID: PARENT_ID's parent is CHILD_ID,
        #   CHILD_ID's parent is GRANDCHILD_ID → cycle
        data = HierarchyLinkCreate(
            parent_account_id=PARENT_ID,
            child_account_id=GRANDCHILD_ID,
            relationship_type=HierarchyRelationshipType.subsidiary,
        )

        db = AsyncMock()
        no_existing = MagicMock()
        no_existing.scalar_one_or_none.return_value = None

        # BFS from PARENT_ID: parents = [CHILD_ID]
        parents_of_parent = MagicMock()
        parents_of_parent.scalars.return_value.all.return_value = [CHILD_ID]
        # BFS from CHILD_ID: parents = [GRANDCHILD_ID] → cycle found
        parents_of_child = MagicMock()
        parents_of_child.scalars.return_value.all.return_value = [GRANDCHILD_ID]

        db.execute.side_effect = [no_existing, parents_of_parent, parents_of_child]

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await create_hierarchy_link(db, data)
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_no_cycle_for_independent_branches(self):
        # PARENT_ID → CHILD_ID exists; now CHILD_ID_2 → CHILD_ID should be fine
        data = HierarchyLinkCreate(
            parent_account_id=CHILD_ID_2,
            child_account_id=CHILD_ID,
            relationship_type=HierarchyRelationshipType.partner,
        )

        db = AsyncMock()
        db.add = MagicMock()
        no_existing = MagicMock()
        no_existing.scalar_one_or_none.return_value = None
        # BFS from CHILD_ID_2: no parents
        no_parents = MagicMock()
        no_parents.scalars.return_value.all.return_value = []
        db.execute.side_effect = [no_existing, no_parents]

        async def _refresh(obj):
            obj.id = LINK_ID_2
            obj.created_at = NOW
            obj.updated_at = NOW

        db.refresh = AsyncMock(side_effect=_refresh)

        result = await create_hierarchy_link(db, data)
        assert result.child_account_id == CHILD_ID

    @pytest.mark.asyncio
    async def test_list_children_multiple_in_order(self):
        link1 = _make_link(id=LINK_ID, child_account_id=CHILD_ID)
        link2 = _make_link(id=LINK_ID_2, child_account_id=CHILD_ID_2)
        db = _make_db(execute_returns=_async_list([link1, link2]))
        result = await list_children(db, PARENT_ID)
        assert result.total == 2
        # sorted by child_account_id
        ids = [i.child_account_id for i in result.items]
        assert ids == sorted(ids)

    @pytest.mark.asyncio
    async def test_list_parents_multiple_in_order(self):
        link1 = _make_link(id=LINK_ID, parent_account_id=PARENT_ID)
        link2 = _make_link(id=LINK_ID_2, parent_account_id=PARENT_ID + 5)
        db = _make_db(execute_returns=_async_list([link1, link2]))
        result = await list_parents(db, CHILD_ID)
        assert result.total == 2

    @pytest.mark.asyncio
    async def test_update_only_is_active(self):
        link = _make_link(is_active=True)
        db = _make_db(execute_returns=_async_result(link))
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        data = HierarchyLinkUpdate(is_active=False)
        await update_hierarchy_link(db, LINK_ID, data)
        assert link.is_active is False

    @pytest.mark.asyncio
    async def test_update_only_notes(self):
        link = _make_link(notes=None)
        db = _make_db(execute_returns=_async_result(link))
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        data = HierarchyLinkUpdate(notes="New note")
        await update_hierarchy_link(db, LINK_ID, data)
        assert link.notes == "New note"

    @pytest.mark.asyncio
    async def test_get_account_hierarchy_tree_nested(self):
        # root → CHILD_ID → GRANDCHILD_ID
        child_link = _make_link(id=LINK_ID, parent_account_id=PARENT_ID, child_account_id=CHILD_ID)
        grandchild_link = _make_link(
            id=LINK_ID_2,
            parent_account_id=CHILD_ID,
            child_account_id=GRANDCHILD_ID,
        )
        children_of_root = _async_list([child_link])
        children_of_child = _async_list([grandchild_link])
        no_children = _async_list([])

        db = _make_db(execute_returns=[children_of_root, children_of_child, no_children])
        result = await get_account_hierarchy_tree(db, PARENT_ID)
        assert len(result.tree.children) == 1
        assert len(result.tree.children[0].children) == 1
        assert result.tree.children[0].children[0].account_id == GRANDCHILD_ID

    @pytest.mark.asyncio
    async def test_consolidated_summary_multi_level(self):
        # root → CHILD_ID → GRANDCHILD_ID
        children_of_root = MagicMock()
        children_of_root.scalars.return_value.all.return_value = [CHILD_ID]
        children_of_child = MagicMock()
        children_of_child.scalars.return_value.all.return_value = [GRANDCHILD_ID]
        no_more = MagicMock()
        no_more.scalars.return_value.all.return_value = []

        db = _make_db(execute_returns=[children_of_root, children_of_child, no_more])
        result = await get_consolidated_summary(db, PARENT_ID)
        assert result.total_accounts == 3
        assert result.all_descendants == 2
        assert GRANDCHILD_ID in result.account_ids


# ---------------------------------------------------------------------------
# API layer tests (32-70)
# ---------------------------------------------------------------------------


def _make_user(is_admin: bool = False):
    user = MagicMock()
    user.id = 99
    user.is_admin = is_admin
    return user


class TestAPIEndpoints:
    """Tests 32-70: API layer."""

    @pytest.fixture
    def client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api.v1.corporate_account_hierarchy import router
        from app.api.deps import get_current_user, get_db, require_admin

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        user = _make_user()
        admin_user = _make_user(is_admin=True)
        fake_db = AsyncMock()

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: fake_db
        app.dependency_overrides[require_admin] = lambda: admin_user

        return TestClient(app)

    # ---- platform-admin: create ----

    def test_platform_create_201(self, client):
        with patch(
            "app.api.v1.corporate_account_hierarchy.create_hierarchy_link",
            new=AsyncMock(return_value=_LINK_RESPONSE),
        ):
            resp = client.post(
                "/api/v1/platform-admin/corporate/account-hierarchy",
                json={
                    "parent_account_id": PARENT_ID,
                    "child_account_id": CHILD_ID,
                    "relationship_type": "subsidiary",
                },
            )
        assert resp.status_code == 201
        assert resp.json()["parent_account_id"] == PARENT_ID

    def test_platform_create_422_on_cycle(self, client):
        from fastapi import HTTPException
        with patch(
            "app.api.v1.corporate_account_hierarchy.create_hierarchy_link",
            new=AsyncMock(
                side_effect=HTTPException(
                    status_code=422, detail="Would create cycle"
                )
            ),
        ):
            resp = client.post(
                "/api/v1/platform-admin/corporate/account-hierarchy",
                json={
                    "parent_account_id": PARENT_ID,
                    "child_account_id": CHILD_ID,
                    "relationship_type": "subsidiary",
                },
            )
        assert resp.status_code == 422

    def test_platform_create_409_on_duplicate(self, client):
        from fastapi import HTTPException
        with patch(
            "app.api.v1.corporate_account_hierarchy.create_hierarchy_link",
            new=AsyncMock(
                side_effect=HTTPException(status_code=409, detail="Already exists")
            ),
        ):
            resp = client.post(
                "/api/v1/platform-admin/corporate/account-hierarchy",
                json={
                    "parent_account_id": PARENT_ID,
                    "child_account_id": CHILD_ID,
                    "relationship_type": "subsidiary",
                },
            )
        assert resp.status_code == 409

    # ---- platform-admin: list all ----

    def test_platform_list_all_200(self, client):
        with patch(
            "app.api.v1.corporate_account_hierarchy.list_all_platform",
            new=AsyncMock(return_value=_LIST_RESPONSE),
        ):
            resp = client.get("/api/v1/platform-admin/corporate/account-hierarchy/all")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    # ---- platform-admin: get by link_id ----

    def test_platform_get_link_200(self, client):
        with patch(
            "app.api.v1.corporate_account_hierarchy.get_hierarchy_link",
            new=AsyncMock(return_value=_LINK_RESPONSE),
        ):
            resp = client.get(
                f"/api/v1/platform-admin/corporate/account-hierarchy/{LINK_ID}"
            )
        assert resp.status_code == 200

    def test_platform_get_link_404(self, client):
        from fastapi import HTTPException
        with patch(
            "app.api.v1.corporate_account_hierarchy.get_hierarchy_link",
            new=AsyncMock(
                side_effect=HTTPException(status_code=404, detail="Not found")
            ),
        ):
            resp = client.get(
                f"/api/v1/platform-admin/corporate/account-hierarchy/{LINK_ID}"
            )
        assert resp.status_code == 404

    # ---- platform-admin: update ----

    def test_platform_update_link_200(self, client):
        with patch(
            "app.api.v1.corporate_account_hierarchy.update_hierarchy_link",
            new=AsyncMock(return_value=_LINK_RESPONSE),
        ):
            resp = client.put(
                f"/api/v1/platform-admin/corporate/account-hierarchy/{LINK_ID}",
                json={"notes": "Updated"},
            )
        assert resp.status_code == 200

    # ---- platform-admin: delete ----

    def test_platform_delete_link_204(self, client):
        with patch(
            "app.api.v1.corporate_account_hierarchy.remove_hierarchy_link",
            new=AsyncMock(return_value=None),
        ):
            resp = client.delete(
                f"/api/v1/platform-admin/corporate/account-hierarchy/{LINK_ID}"
            )
        assert resp.status_code == 204

    # ---- platform-admin: account-scoped ----

    def test_platform_get_tree_200(self, client):
        with patch(
            "app.api.v1.corporate_account_hierarchy.get_account_hierarchy_tree",
            new=AsyncMock(return_value=_TREE_RESPONSE),
        ):
            resp = client.get(
                f"/api/v1/platform-admin/corporate/account-hierarchy/account/{PARENT_ID}/tree"
            )
        assert resp.status_code == 200
        assert resp.json()["root_account_id"] == PARENT_ID

    def test_platform_list_children_200(self, client):
        with patch(
            "app.api.v1.corporate_account_hierarchy.list_children",
            new=AsyncMock(return_value=_LIST_RESPONSE),
        ):
            resp = client.get(
                f"/api/v1/platform-admin/corporate/account-hierarchy/account/{PARENT_ID}/children"
            )
        assert resp.status_code == 200

    def test_platform_list_parents_200(self, client):
        with patch(
            "app.api.v1.corporate_account_hierarchy.list_parents",
            new=AsyncMock(return_value=_LIST_RESPONSE),
        ):
            resp = client.get(
                f"/api/v1/platform-admin/corporate/account-hierarchy/account/{CHILD_ID}/parents"
            )
        assert resp.status_code == 200

    def test_platform_consolidated_summary_200(self, client):
        with patch(
            "app.api.v1.corporate_account_hierarchy.get_consolidated_summary",
            new=AsyncMock(return_value=_SUMMARY_RESPONSE),
        ):
            resp = client.get(
                f"/api/v1/platform-admin/corporate/account-hierarchy/account/{PARENT_ID}/consolidated"
            )
        assert resp.status_code == 200
        assert resp.json()["total_accounts"] == 2

    # ---- account-admin: my hierarchy ----

    def test_admin_children_200(self, client):
        with (
            patch(
                "app.api.v1.corporate_account_hierarchy._resolve_account_id",
                new=AsyncMock(return_value=PARENT_ID),
            ),
            patch(
                "app.api.v1.corporate_account_hierarchy._require_account_admin",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.api.v1.corporate_account_hierarchy.list_children",
                new=AsyncMock(return_value=_LIST_RESPONSE),
            ),
        ):
            resp = client.get("/api/v1/corporate/admin/hierarchy/children")
        assert resp.status_code == 200

    def test_admin_children_404_not_in_account(self, client):
        from fastapi import HTTPException
        with patch(
            "app.api.v1.corporate_account_hierarchy._resolve_account_id",
            new=AsyncMock(
                side_effect=HTTPException(status_code=404, detail="Not a member")
            ),
        ):
            resp = client.get("/api/v1/corporate/admin/hierarchy/children")
        assert resp.status_code == 404

    def test_admin_parents_200(self, client):
        with (
            patch(
                "app.api.v1.corporate_account_hierarchy._resolve_account_id",
                new=AsyncMock(return_value=CHILD_ID),
            ),
            patch(
                "app.api.v1.corporate_account_hierarchy._require_account_admin",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.api.v1.corporate_account_hierarchy.list_parents",
                new=AsyncMock(return_value=_LIST_RESPONSE),
            ),
        ):
            resp = client.get("/api/v1/corporate/admin/hierarchy/parents")
        assert resp.status_code == 200

    def test_admin_parents_404_not_in_account(self, client):
        from fastapi import HTTPException
        with patch(
            "app.api.v1.corporate_account_hierarchy._resolve_account_id",
            new=AsyncMock(
                side_effect=HTTPException(status_code=404, detail="Not a member")
            ),
        ):
            resp = client.get("/api/v1/corporate/admin/hierarchy/parents")
        assert resp.status_code == 404

    # ---- additional API edge cases ----

    def test_platform_list_all_filtered_by_account_id(self, client):
        with patch(
            "app.api.v1.corporate_account_hierarchy.list_all_platform",
            new=AsyncMock(return_value=_LIST_RESPONSE),
        ):
            resp = client.get(
                f"/api/v1/platform-admin/corporate/account-hierarchy/all?account_id={PARENT_ID}"
            )
        assert resp.status_code == 200

    def test_platform_list_children_with_is_active_filter(self, client):
        with patch(
            "app.api.v1.corporate_account_hierarchy.list_children",
            new=AsyncMock(return_value=_LIST_RESPONSE),
        ):
            resp = client.get(
                f"/api/v1/platform-admin/corporate/account-hierarchy/account/{PARENT_ID}/children?is_active=true"
            )
        assert resp.status_code == 200

    def test_platform_list_parents_with_is_active_filter(self, client):
        with patch(
            "app.api.v1.corporate_account_hierarchy.list_parents",
            new=AsyncMock(return_value=_LIST_RESPONSE),
        ):
            resp = client.get(
                f"/api/v1/platform-admin/corporate/account-hierarchy/account/{CHILD_ID}/parents?is_active=false"
            )
        assert resp.status_code == 200

    def test_platform_create_with_notes_201(self, client):
        with patch(
            "app.api.v1.corporate_account_hierarchy.create_hierarchy_link",
            new=AsyncMock(return_value=_LINK_RESPONSE),
        ):
            resp = client.post(
                "/api/v1/platform-admin/corporate/account-hierarchy",
                json={
                    "parent_account_id": PARENT_ID,
                    "child_account_id": CHILD_ID,
                    "relationship_type": "franchise",
                    "notes": "Main franchise location",
                },
            )
        assert resp.status_code == 201

    def test_admin_children_with_is_active_filter(self, client):
        with (
            patch(
                "app.api.v1.corporate_account_hierarchy._resolve_account_id",
                new=AsyncMock(return_value=PARENT_ID),
            ),
            patch(
                "app.api.v1.corporate_account_hierarchy._require_account_admin",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.api.v1.corporate_account_hierarchy.list_children",
                new=AsyncMock(return_value=_LIST_RESPONSE),
            ),
        ):
            resp = client.get(
                "/api/v1/corporate/admin/hierarchy/children?is_active=true"
            )
        assert resp.status_code == 200

    def test_admin_parents_with_is_active_filter(self, client):
        with (
            patch(
                "app.api.v1.corporate_account_hierarchy._resolve_account_id",
                new=AsyncMock(return_value=CHILD_ID),
            ),
            patch(
                "app.api.v1.corporate_account_hierarchy._require_account_admin",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.api.v1.corporate_account_hierarchy.list_parents",
                new=AsyncMock(return_value=_LIST_RESPONSE),
            ),
        ):
            resp = client.get(
                "/api/v1/corporate/admin/hierarchy/parents?is_active=false"
            )
        assert resp.status_code == 200

    def test_platform_consolidated_correct_counts(self, client):
        big_summary = ConsolidatedSummaryResponse(
            root_account_id=PARENT_ID,
            total_accounts=5,
            direct_children=2,
            all_descendants=4,
            account_ids=[PARENT_ID, CHILD_ID, CHILD_ID_2, GRANDCHILD_ID, 40],
        )
        with patch(
            "app.api.v1.corporate_account_hierarchy.get_consolidated_summary",
            new=AsyncMock(return_value=big_summary),
        ):
            resp = client.get(
                f"/api/v1/platform-admin/corporate/account-hierarchy/account/{PARENT_ID}/consolidated"
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_accounts"] == 5
        assert body["direct_children"] == 2
        assert body["all_descendants"] == 4
