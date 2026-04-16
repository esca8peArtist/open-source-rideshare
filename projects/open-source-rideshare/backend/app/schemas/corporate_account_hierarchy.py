"""Pydantic schemas for Corporate Account Hierarchy.

Schemas:
  HierarchyLinkCreate           — POST body to create a parent→child link
  HierarchyLinkUpdate           — PUT body for partial updates
  HierarchyLinkResponse         — full link representation
  HierarchyLinkListResponse     — paginated list of links
  HierarchyTreeNode             — recursive node in a hierarchy tree
  HierarchyTreeResponse         — full tree rooted at one account
  ConsolidatedSummaryResponse   — aggregate counts for a hierarchy
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel

from app.models.corporate_account_hierarchy import HierarchyRelationshipType


# ---------------------------------------------------------------------------
# Create / update
# ---------------------------------------------------------------------------


class HierarchyLinkCreate(BaseModel):
    """Fields required to create a new account hierarchy link."""

    parent_account_id: int
    child_account_id: int
    relationship_type: HierarchyRelationshipType
    notes: Optional[str] = None
    is_active: bool = True


class HierarchyLinkUpdate(BaseModel):
    """All fields optional for partial updates to a hierarchy link."""

    relationship_type: Optional[HierarchyRelationshipType] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class HierarchyLinkResponse(BaseModel):
    """Full representation of a corporate account hierarchy link."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    parent_account_id: int
    child_account_id: int
    relationship_type: HierarchyRelationshipType
    notes: Optional[str] = None
    created_by_id: Optional[int] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class HierarchyLinkListResponse(BaseModel):
    """Paginated list of corporate account hierarchy links."""

    items: List[HierarchyLinkResponse]
    total: int


class HierarchyTreeNode(BaseModel):
    """A single node in a hierarchy tree, with nested children."""

    account_id: int
    relationship_type: Optional[HierarchyRelationshipType] = None
    link_id: Optional[uuid.UUID] = None
    children: List["HierarchyTreeNode"] = []


# Required for self-referential Pydantic models.
HierarchyTreeNode.model_rebuild()


class HierarchyTreeResponse(BaseModel):
    """Full hierarchy tree rooted at one corporate account."""

    root_account_id: int
    tree: HierarchyTreeNode


class ConsolidatedSummaryResponse(BaseModel):
    """Aggregate counts for a corporate account hierarchy.

    Attributes:
        root_account_id: The account at the top of the queried hierarchy.
        total_accounts: Root account plus all descendants.
        direct_children: Number of immediate children of root.
        all_descendants: Total descendant accounts (excluding root).
        account_ids: All account IDs in the hierarchy (root + all descendants).
    """

    root_account_id: int
    total_accounts: int
    direct_children: int
    all_descendants: int
    account_ids: List[int]
