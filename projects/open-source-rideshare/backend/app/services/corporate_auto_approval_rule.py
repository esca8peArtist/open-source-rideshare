"""Service layer for Corporate Auto-Approval Rules.

Admins configure rules that, when all their non-null conditions match a ride
request, automatically approve that ride without a manual approval step.
Multiple rules per account are supported; if ANY active rule matches, the
ride is considered auto-approved.  Rules are evaluated in descending priority
order (ties broken by created_at ASC).

Public surface
--------------
create_auto_approval_rule(db, account_id, creator_id, data)
get_auto_approval_rule(db, rule_id, account_id)
list_auto_approval_rules(db, account_id, is_active=None)
update_auto_approval_rule(db, rule_id, account_id, data)
activate_auto_approval_rule(db, rule_id, account_id)
deactivate_auto_approval_rule(db, rule_id, account_id)
delete_auto_approval_rule(db, rule_id, account_id)
evaluate_auto_approval(db, account_id, member_id, estimated_cost_usd, ...)
list_all_auto_approval_rules_platform(db, skip=0, limit=100)
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_auto_approval_rule import CorporateAutoApprovalRule
from app.models.corporate_employee_group import CorporateGroupMembership


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_rule(
    db: AsyncSession, rule_id: int, account_id: int
) -> CorporateAutoApprovalRule:
    """Fetch a rule; raise 404 if not found or account mismatch."""
    result = await db.execute(
        select(CorporateAutoApprovalRule).where(
            CorporateAutoApprovalRule.id == rule_id,
            CorporateAutoApprovalRule.account_id == account_id,
        )
    )
    rule = result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Auto-approval rule not found.",
        )
    return rule


async def _check_name_conflict(
    db: AsyncSession,
    account_id: int,
    name: str,
    exclude_rule_id: int | None = None,
) -> None:
    """Raise 409 if an active rule with the same name already exists.

    When exclude_rule_id is supplied the rule with that ID is ignored (used
    during updates so a rule can keep its own name without triggering the
    conflict check).
    """
    q = select(CorporateAutoApprovalRule).where(
        CorporateAutoApprovalRule.account_id == account_id,
        CorporateAutoApprovalRule.name == name,
        CorporateAutoApprovalRule.is_active.is_(True),
    )
    if exclude_rule_id is not None:
        q = q.where(CorporateAutoApprovalRule.id != exclude_rule_id)

    result = await db.execute(q)
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An active auto-approval rule named '{name}' already exists for this account.",
        )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def create_auto_approval_rule(
    db: AsyncSession,
    account_id: int,
    creator_id: int,
    data,
) -> CorporateAutoApprovalRule:
    """Create a new auto-approval rule for a corporate account.

    Rules:
    - 409 if an active rule with the same name already exists for this account.
    - start_hour and end_hour must both be set or both null (validated by schema,
      enforced here as a defence-in-depth check).

    Args:
        db:         Async database session.
        account_id: The corporate account to attach the rule to.
        creator_id: User ID of the admin creating the rule.
        data:       AutoApprovalRuleCreate schema instance.

    Returns:
        The newly created CorporateAutoApprovalRule.

    Raises:
        HTTPException 400: start_hour/end_hour mismatch.
        HTTPException 409: Duplicate active rule name.
    """
    if (data.start_hour is None) != (data.end_hour is None):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_hour and end_hour must both be set or both be null.",
        )

    await _check_name_conflict(db, account_id, data.name)

    rule = CorporateAutoApprovalRule(
        account_id=account_id,
        created_by_id=creator_id,
        name=data.name,
        is_active=data.is_active,
        max_cost_usd=data.max_cost_usd,
        trip_purpose_ids=data.trip_purpose_ids,
        cost_center_ids=data.cost_center_ids,
        employee_group_ids=data.employee_group_ids,
        allowed_days_of_week=data.allowed_days_of_week,
        start_hour=data.start_hour,
        end_hour=data.end_hour,
        priority=data.priority,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


async def get_auto_approval_rule(
    db: AsyncSession,
    rule_id: int,
    account_id: int,
) -> CorporateAutoApprovalRule:
    """Return a single auto-approval rule, scoped to the account.

    Raises:
        HTTPException 404: Rule not found or belongs to a different account.
    """
    return await _get_rule(db, rule_id, account_id)


async def list_auto_approval_rules(
    db: AsyncSession,
    account_id: int,
    is_active: bool | None = None,
) -> list[CorporateAutoApprovalRule]:
    """Return all auto-approval rules for an account, ordered by priority DESC.

    Args:
        db:         Async database session.
        account_id: The corporate account to query.
        is_active:  Optional filter; pass True or False to restrict results.

    Returns:
        List of rules ordered by priority DESC, created_at ASC.
    """
    q = select(CorporateAutoApprovalRule).where(
        CorporateAutoApprovalRule.account_id == account_id
    )
    if is_active is not None:
        q = q.where(CorporateAutoApprovalRule.is_active.is_(is_active))
    q = q.order_by(
        CorporateAutoApprovalRule.priority.desc(),
        CorporateAutoApprovalRule.created_at.asc(),
    )
    result = await db.execute(q)
    return list(result.scalars().all())


async def update_auto_approval_rule(
    db: AsyncSession,
    rule_id: int,
    account_id: int,
    data,
) -> CorporateAutoApprovalRule:
    """Update an existing auto-approval rule.

    Only supplied (non-None) fields are applied.

    Raises:
        HTTPException 404: Rule not found.
        HTTPException 409: Name collision with a different active rule.
    """
    rule = await _get_rule(db, rule_id, account_id)

    if data.name is not None and data.name != rule.name:
        await _check_name_conflict(db, account_id, data.name, exclude_rule_id=rule_id)
        rule.name = data.name

    if data.is_active is not None:
        rule.is_active = data.is_active
    if data.max_cost_usd is not None:
        rule.max_cost_usd = data.max_cost_usd
    if data.trip_purpose_ids is not None:
        rule.trip_purpose_ids = data.trip_purpose_ids
    if data.cost_center_ids is not None:
        rule.cost_center_ids = data.cost_center_ids
    if data.employee_group_ids is not None:
        rule.employee_group_ids = data.employee_group_ids
    if data.allowed_days_of_week is not None:
        rule.allowed_days_of_week = data.allowed_days_of_week
    if data.start_hour is not None:
        rule.start_hour = data.start_hour
    if data.end_hour is not None:
        rule.end_hour = data.end_hour
    if data.priority is not None:
        rule.priority = data.priority

    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


async def activate_auto_approval_rule(
    db: AsyncSession,
    rule_id: int,
    account_id: int,
) -> CorporateAutoApprovalRule:
    """Activate an auto-approval rule.

    Raises:
        HTTPException 404: Rule not found.
        HTTPException 409: Rule is already active.
    """
    rule = await _get_rule(db, rule_id, account_id)
    if rule.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Auto-approval rule is already active.",
        )
    rule.is_active = True
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


async def deactivate_auto_approval_rule(
    db: AsyncSession,
    rule_id: int,
    account_id: int,
) -> CorporateAutoApprovalRule:
    """Deactivate an auto-approval rule.

    Raises:
        HTTPException 404: Rule not found.
        HTTPException 409: Rule is already inactive.
    """
    rule = await _get_rule(db, rule_id, account_id)
    if not rule.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Auto-approval rule is already inactive.",
        )
    rule.is_active = False
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


async def delete_auto_approval_rule(
    db: AsyncSession,
    rule_id: int,
    account_id: int,
) -> None:
    """Hard-delete an auto-approval rule.

    Raises:
        HTTPException 404: Rule not found.
    """
    rule = await _get_rule(db, rule_id, account_id)
    await db.delete(rule)
    await db.commit()


# ---------------------------------------------------------------------------
# Evaluation engine
# ---------------------------------------------------------------------------


async def evaluate_auto_approval(
    db: AsyncSession,
    account_id: int,
    member_id: int,
    estimated_cost_usd: float,
    trip_purpose_id: Optional[int] = None,
    cost_center_id: Optional[int] = None,
    ride_dt: Optional[datetime] = None,
) -> tuple[bool, CorporateAutoApprovalRule | None]:
    """Evaluate whether a ride qualifies for auto-approval.

    Loads all active rules for the account, ordered by priority DESC then
    created_at ASC, and returns the first rule where every non-null condition
    is satisfied.

    Condition checks:
    - max_cost_usd:         estimated_cost_usd <= rule.max_cost_usd
    - trip_purpose_ids:     trip_purpose_id in rule.trip_purpose_ids
    - cost_center_ids:      cost_center_id in rule.cost_center_ids
    - employee_group_ids:   member has a CorporateGroupMembership in one of the
                            groups, filtered by account_id
    - allowed_days_of_week: ride_dt.weekday() in rule.allowed_days_of_week
    - start_hour/end_hour:  start_hour <= ride_dt.hour <= end_hour

    Args:
        db:                 Async database session.
        account_id:         Corporate account whose rules are evaluated.
        member_id:          ID of the CorporateAccountMember requesting the ride.
        estimated_cost_usd: Estimated fare.
        trip_purpose_id:    Trip purpose (optional).
        cost_center_id:     Cost center (optional).
        ride_dt:            Proposed ride datetime (UTC); defaults to utcnow().

    Returns:
        (True, matching_rule) if a rule matches, (False, None) otherwise.
    """
    if ride_dt is None:
        ride_dt = datetime.now(tz=timezone.utc)

    # Load all active rules, priority DESC / created_at ASC
    result = await db.execute(
        select(CorporateAutoApprovalRule).where(
            CorporateAutoApprovalRule.account_id == account_id,
            CorporateAutoApprovalRule.is_active.is_(True),
        ).order_by(
            CorporateAutoApprovalRule.priority.desc(),
            CorporateAutoApprovalRule.created_at.asc(),
        )
    )
    active_rules = list(result.scalars().all())

    # Pre-fetch group memberships for this member (only once)
    member_group_ids: set[int] | None = None

    for rule in active_rules:
        # --- max_cost_usd ---
        if rule.max_cost_usd is not None:
            if Decimal(str(estimated_cost_usd)) > Decimal(str(rule.max_cost_usd)):
                continue

        # --- trip_purpose_ids ---
        if rule.trip_purpose_ids is not None:
            if trip_purpose_id not in rule.trip_purpose_ids:
                continue

        # --- cost_center_ids ---
        if rule.cost_center_ids is not None:
            if cost_center_id not in rule.cost_center_ids:
                continue

        # --- employee_group_ids ---
        if rule.employee_group_ids is not None:
            if member_group_ids is None:
                member_group_ids = await _get_member_group_ids(db, member_id)
            if not member_group_ids.intersection(rule.employee_group_ids):
                continue

        # --- allowed_days_of_week ---
        if rule.allowed_days_of_week is not None:
            if ride_dt.weekday() not in rule.allowed_days_of_week:
                continue

        # --- start_hour / end_hour ---
        if rule.start_hour is not None and rule.end_hour is not None:
            if not (rule.start_hour <= ride_dt.hour <= rule.end_hour):
                continue

        # All conditions satisfied — rule matches
        return True, rule

    return False, None


async def _get_member_group_ids(db: AsyncSession, member_id: int) -> set[int]:
    """Return the set of CorporateEmployeeGroup IDs the member belongs to."""
    result = await db.execute(
        select(CorporateGroupMembership.group_id).where(
            CorporateGroupMembership.member_id == member_id,
        )
    )
    return {row[0] for row in result.all()}


# ---------------------------------------------------------------------------
# Platform-admin helpers
# ---------------------------------------------------------------------------


async def list_all_auto_approval_rules_platform(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 100,
) -> list[CorporateAutoApprovalRule]:
    """Return all auto-approval rules across all accounts (newest first).

    Platform-admin use only.

    Args:
        db:    Async database session.
        skip:  Pagination offset.
        limit: Maximum records to return.

    Returns:
        List of CorporateAutoApprovalRule ordered by created_at DESC.
    """
    result = await db.execute(
        select(CorporateAutoApprovalRule)
        .order_by(CorporateAutoApprovalRule.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())
