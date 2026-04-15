"""Pydantic v2 schemas for Corporate Multi-Level Approval Chains.

Approval chains let corporate account admins define configurable multi-step
approval workflows.  Rides matching chain criteria must be approved by a
sequence of admins before the employee can book.

Public surface
--------------
ApproverType           — enum: specific_user / any_admin.
EscalationAction       — enum: skip / deny.
ApprovalChainStepCreate — request body for a single chain step.
ApprovalChainCreate    — request body for creating a full chain with steps.
ApprovalChainUpdate    — request body for partial chain updates.
ChainRequestCreate     — request body for starting an approval request.
StepDecisionRequest    — request body for recording a step decision.

ApprovalChainStepResponse    — single step returned by the API.
ApprovalChainResponse        — full chain with steps returned by the API.
ApprovalChainListResponse    — paginated list of chains.
StepDecisionResponse         — single step decision returned by the API.
ChainRequestResponse         — full request with decisions returned by the API.
ChainRequestListResponse     — paginated list of chain requests.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ApproverType(str, Enum):
    """Who is authorised to approve a specific chain step."""

    specific_user = "specific_user"
    any_admin = "any_admin"


class EscalationAction(str, Enum):
    """Action taken automatically when a step's timeout_hours elapses."""

    skip = "skip"
    deny = "deny"


class RequestStatus(str, Enum):
    """Lifecycle status of a chain approval request."""

    pending = "pending"
    approved = "approved"
    denied = "denied"
    cancelled = "cancelled"


class StepDecision(str, Enum):
    """Decision recorded on a single step."""

    approved = "approved"
    denied = "denied"


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class ApprovalChainStepCreate(BaseModel):
    """Request body for a single step within an approval chain.

    Attributes:
        step_order:        1-based position; must be sequential from 1.
        approver_type:     Whether a specific user or any account admin must
                           approve this step.
        approver_user_id:  Required when approver_type=specific_user.
        timeout_hours:     Hours until escalation fires; None means no timeout.
        escalation_action: "skip" auto-approves this step on timeout; "deny"
                           closes the whole request as denied.
        description:       Optional human note for this step.
    """

    step_order: int = Field(..., ge=1)
    approver_type: ApproverType
    approver_user_id: Optional[int] = None
    timeout_hours: Optional[int] = Field(None, ge=1)
    escalation_action: EscalationAction = EscalationAction.deny
    description: Optional[str] = Field(None, max_length=200)


class ApprovalChainCreate(BaseModel):
    """Request body for creating a new approval chain.

    Attributes:
        name:                         Chain display name (max 100 chars).
        description:                  Optional description (max 300 chars).
        min_cost_usd:                 Chain applies when estimated ride cost >=
                                      this value; None means applies regardless.
        applies_to_all_cost_centers:  When False, only cost centers listed in
                                      cost_center_ids are subject to this chain.
        cost_center_ids:              List of cost center IDs to restrict to
                                      (only relevant when
                                      applies_to_all_cost_centers=False).
        steps:                        Ordered list of steps (1 to 5).
    """

    name: str = Field(..., max_length=100)
    description: Optional[str] = Field(None, max_length=300)
    min_cost_usd: Optional[float] = Field(None, ge=0)
    applies_to_all_cost_centers: bool = True
    cost_center_ids: Optional[List[int]] = None
    steps: List[ApprovalChainStepCreate] = Field(..., min_length=1, max_length=5)


class ApprovalChainUpdate(BaseModel):
    """Request body for partially updating an approval chain.

    All fields are optional.  When ``steps`` is provided the existing steps are
    replaced entirely.

    Attributes:
        name:                         New display name.
        description:                  New description.
        min_cost_usd:                 New minimum cost threshold.
        applies_to_all_cost_centers:  Updated cost-center scope flag.
        cost_center_ids:              Replacement cost-center ID list.
        is_active:                    Activate or deactivate the chain.
        steps:                        Replacement step list (1 to 5).
    """

    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = Field(None, max_length=300)
    min_cost_usd: Optional[float] = Field(None, ge=0)
    applies_to_all_cost_centers: Optional[bool] = None
    cost_center_ids: Optional[List[int]] = None
    is_active: Optional[bool] = None
    steps: Optional[List[ApprovalChainStepCreate]] = Field(
        None, min_length=1, max_length=5
    )


class ChainRequestCreate(BaseModel):
    """Request body for starting a multi-step approval request.

    Attributes:
        chain_id:                ID of the approval chain to run.
        estimated_cost_usd:      Optional estimated ride cost.
        cost_center_id:          Optional cost center FK.
        purpose:                 Optional purpose description (max 200 chars).
        destination_description: Optional destination note (max 300 chars).
    """

    chain_id: int
    estimated_cost_usd: Optional[float] = Field(None, ge=0)
    cost_center_id: Optional[int] = None
    purpose: Optional[str] = Field(None, max_length=200)
    destination_description: Optional[str] = Field(None, max_length=300)


class StepDecisionRequest(BaseModel):
    """Request body for recording a decision on the current chain step.

    Attributes:
        decision: "approved" to advance the request, "denied" to close it.
        note:     Optional note from the approver (max 500 chars).
    """

    decision: StepDecision
    note: Optional[str] = Field(None, max_length=500)


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class ApprovalChainStepResponse(BaseModel):
    """A single approval chain step as returned by the API.

    Attributes:
        id:               Primary key.
        chain_id:         Parent chain FK.
        step_order:       1-based position in the chain.
        approver_type:    "specific_user" or "any_admin".
        approver_user_id: Approver FK (null for any_admin steps).
        timeout_hours:    Hours until escalation; null means no timeout.
        escalation_action: "skip" or "deny" on timeout.
        description:      Optional step note.
    """

    model_config = {"from_attributes": True}

    id: int
    chain_id: int
    step_order: int
    approver_type: str
    approver_user_id: Optional[int]
    timeout_hours: Optional[int]
    escalation_action: str
    description: Optional[str]


class ApprovalChainResponse(BaseModel):
    """A full approval chain with its steps as returned by the API.

    Attributes:
        id:                         Primary key.
        account_id:                 Owning corporate account FK.
        name:                       Display name.
        description:                Optional description.
        min_cost_usd:               Minimum cost threshold (null = no threshold).
        applies_to_all_cost_centers: True when chain applies to all cost centers.
        cost_center_ids:            Restricted cost center ID list.
        is_active:                  Whether the chain is currently enforced.
        created_by_id:              Admin who created the chain.
        created_at:                 Creation timestamp.
        updated_at:                 Last-modified timestamp.
        steps:                      Ordered list of chain steps.
    """

    model_config = {"from_attributes": True}

    id: int
    account_id: int
    name: str
    description: Optional[str]
    min_cost_usd: Optional[float]
    applies_to_all_cost_centers: bool
    cost_center_ids: Optional[List[int]]
    is_active: bool
    created_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime
    steps: List[ApprovalChainStepResponse]


class ApprovalChainListResponse(BaseModel):
    """Paginated list of approval chains.

    Attributes:
        chains: Chain records.
        total:  Number of records returned.
    """

    chains: List[ApprovalChainResponse]
    total: int


class StepDecisionResponse(BaseModel):
    """A single per-step decision as returned by the API.

    Attributes:
        id:          Primary key.
        request_id:  Parent request FK.
        step_order:  Step this decision was made on.
        approver_id: User who made the decision (null if system/timeout).
        decision:    "approved", "denied", or "skipped".
        note:        Optional note.
        decided_at:  When the decision was recorded.
    """

    model_config = {"from_attributes": True}

    id: int
    request_id: int
    step_order: int
    approver_id: Optional[int]
    decision: str
    note: Optional[str]
    decided_at: datetime


class ChainRequestResponse(BaseModel):
    """A full approval request with its step decisions as returned by the API.

    Attributes:
        id:                      Primary key.
        chain_id:                Chain FK (null if chain was deleted).
        account_id:              Corporate account FK.
        requester_id:            Employee who submitted the request.
        current_step_order:      Step currently awaiting a decision.
        status:                  "pending", "approved", "denied", or "cancelled".
        estimated_cost_usd:      Optional estimated ride cost.
        cost_center_id:          Optional cost center FK.
        purpose:                 Optional purpose note.
        destination_description: Optional destination note.
        final_decision_at:       When the request reached a terminal status.
        final_decision_by_id:    Who made the final decision.
        created_at:              Creation timestamp.
        decisions:               Decisions recorded so far.
        total_steps:             Total number of steps in the chain at creation time.
    """

    model_config = {"from_attributes": True}

    id: int
    chain_id: Optional[int]
    account_id: int
    requester_id: Optional[int]
    current_step_order: int
    status: str
    estimated_cost_usd: Optional[float]
    cost_center_id: Optional[int]
    purpose: Optional[str]
    destination_description: Optional[str]
    final_decision_at: Optional[datetime]
    final_decision_by_id: Optional[int]
    created_at: datetime
    decisions: List[StepDecisionResponse]
    total_steps: int


class ChainRequestListResponse(BaseModel):
    """Paginated list of approval chain requests.

    Attributes:
        requests: Request records.
        total:    Number of records returned.
    """

    requests: List[ChainRequestResponse]
    total: int
