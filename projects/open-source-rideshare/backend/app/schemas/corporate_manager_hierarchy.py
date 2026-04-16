"""Pydantic v2 schemas for Corporate Manager Hierarchy.

Enterprise admins define employee reporting relationships (direct and
dotted-line) within a corporate account.

Public surface
--------------
RelationshipType           — enum: direct | dotted_line
ManagerRelationshipCreate  — request body for creating a relationship.
ManagerRelationshipUpdate  — request body for updating notes / is_active.
ManagerRelationshipResponse — single relationship record returned by the API.
ManagerRelationshipListResponse — list wrapper.
ReportingChainResponse     — ordered list of managers from employee to root.
OrgSummaryResponse         — account-level org chart statistics.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RelationshipType(str, Enum):
    """Type of manager relationship."""

    direct = "direct"
    dotted_line = "dotted_line"


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class ManagerRelationshipCreate(BaseModel):
    """Request body for creating a manager relationship.

    Attributes:
        employee_member_id:  ID of the corporate_account_members row for the
                             subordinate.
        manager_member_id:   ID of the corporate_account_members row for the
                             manager.
        relationship_type:   "direct" (default) or "dotted_line".
        notes:               Optional free-text context (max 300 chars).
    """

    employee_member_id: int = Field(..., description="Member ID of the subordinate")
    manager_member_id: int = Field(..., description="Member ID of the manager")
    relationship_type: RelationshipType = RelationshipType.direct
    notes: Optional[str] = Field(None, max_length=300)


class ManagerRelationshipUpdate(BaseModel):
    """Request body for updating an existing relationship.

    All fields optional.  Only supplied fields are written.

    Attributes:
        notes:     Updated notes (max 300 chars); pass ``null`` to clear.
        is_active: Set False to soft-deactivate, True to reactivate.
    """

    notes: Optional[str] = Field(None, max_length=300)
    is_active: Optional[bool] = None


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class ManagerRelationshipResponse(BaseModel):
    """A single manager relationship record.

    Attributes:
        id:                  Primary key.
        account_id:          Corporate account this relationship belongs to.
        employee_member_id:  The subordinate member ID.
        manager_member_id:   The manager member ID.
        relationship_type:   "direct" or "dotted_line".
        notes:               Optional free-text note.
        is_active:           Whether the relationship is currently active.
        created_by_id:       User who created the relationship (null if deleted).
        created_at:          Creation timestamp.
        updated_at:          Last-modified timestamp.
    """

    model_config = {"from_attributes": True}

    id: int
    account_id: int
    employee_member_id: int
    manager_member_id: int
    relationship_type: RelationshipType
    notes: Optional[str]
    is_active: bool
    created_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime


class ManagerRelationshipListResponse(BaseModel):
    """List of manager relationship records.

    Attributes:
        relationships: The relationship records.
        total:         Total count of records in the result set.
    """

    relationships: List[ManagerRelationshipResponse]
    total: int


class ReportingChainEntry(BaseModel):
    """One step in an employee's reporting chain.

    Attributes:
        member_id:         The corporate_account_members row ID.
        relationship_type: How this entry connects to the step below it.
        depth:             0 = direct manager, 1 = manager's manager, etc.
    """

    member_id: int
    relationship_type: RelationshipType
    depth: int


class ReportingChainResponse(BaseModel):
    """The full upward reporting chain for a given employee.

    Attributes:
        employee_member_id: The starting employee.
        chain:              Ordered list from direct manager (depth=0) up to
                            the root.  Empty list if the employee has no
                            managers.
    """

    employee_member_id: int
    chain: List[ReportingChainEntry]


class OrgSummaryResponse(BaseModel):
    """Account-level org chart statistics.

    Attributes:
        account_id:                 The corporate account.
        total_active_relationships: Count of all active relationship rows.
        direct_relationships:       Count of active direct relationships.
        dotted_line_relationships:  Count of active dotted-line relationships.
        members_with_direct_manager: How many members have a direct manager set.
        members_who_are_managers:   How many distinct members are listed as
                                    managers in at least one active relationship.
        top_level_managers:         Members who manage others but have no
                                    direct manager themselves.
    """

    account_id: int
    total_active_relationships: int
    direct_relationships: int
    dotted_line_relationships: int
    members_with_direct_manager: int
    members_who_are_managers: int
    top_level_managers: List[int]
