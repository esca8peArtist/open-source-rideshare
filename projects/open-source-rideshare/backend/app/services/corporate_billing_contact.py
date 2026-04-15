"""Service layer for Corporate Billing Contact Management.

Enterprise accounts may designate billing contacts who receive invoices and
financial notifications.  Billing contacts do not need to be platform users —
email-only contacts are valid.

Public surface
--------------
add_billing_contact(db, account_id, user_id, data)
get_billing_contact(db, account_id, contact_id)
list_billing_contacts(db, account_id, active_only=True, skip=0, limit=50)
update_billing_contact(db, account_id, contact_id, user_id, data)
deactivate_billing_contact(db, account_id, contact_id, user_id)
list_contacts_for_notification(db, account_id, notification_type)
"""
from __future__ import annotations

from typing import Literal, Sequence

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate import BusinessAccountMember, MemberRole
from app.models.corporate_billing_contact import CorporateBillingContact
from app.schemas.corporate_billing_contact import (
    BillingContactCreate,
    BillingContactListResponse,
    BillingContactResponse,
    BillingContactUpdate,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _require_admin(
    db: AsyncSession,
    account_id: int,
    user_id: int,
) -> BusinessAccountMember:
    """Return the member row or raise HTTP 403 if the user is not an admin."""
    result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.user_id == user_id,
            BusinessAccountMember.role == MemberRole.ADMIN,
            BusinessAccountMember.is_active.is_(True),
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have admin access to this corporate account.",
        )
    return member


async def _get_contact(
    db: AsyncSession,
    account_id: int,
    contact_id: int,
) -> CorporateBillingContact:
    """Return the contact or raise HTTP 404 if not found in this account."""
    result = await db.execute(
        select(CorporateBillingContact).where(
            CorporateBillingContact.id == contact_id,
            CorporateBillingContact.account_id == account_id,
        )
    )
    contact = result.scalar_one_or_none()
    if contact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Billing contact not found in this account.",
        )
    return contact


def _contact_to_response(contact: CorporateBillingContact) -> BillingContactResponse:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    return BillingContactResponse(
        id=contact.id,
        account_id=contact.account_id,
        name=contact.name,
        email=contact.email,
        phone=contact.phone,
        role=contact.role,
        receives_invoices=contact.receives_invoices,
        receives_budget_alerts=contact.receives_budget_alerts,
        receives_monthly_summary=contact.receives_monthly_summary,
        is_active=contact.is_active,
        added_by_id=contact.added_by_id,
        created_at=contact.created_at or now,
        updated_at=contact.updated_at or now,
    )


# ---------------------------------------------------------------------------
# Service functions
# ---------------------------------------------------------------------------


async def add_billing_contact(
    db: AsyncSession,
    account_id: int,
    user_id: int,
    data: BillingContactCreate,
) -> BillingContactResponse:
    """Add a new billing contact to a corporate account (admin only).

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        user_id: ID of the requesting admin.
        data: BillingContactCreate payload.

    Returns:
        BillingContactResponse for the newly created contact.

    Raises:
        HTTP 403: When the user is not an account admin.
        HTTP 409: When a contact with the same email already exists in this
            account.
    """
    await _require_admin(db, account_id, user_id)

    normalised_email = data.email.lower()

    # Duplicate email guard per account
    dup_result = await db.execute(
        select(CorporateBillingContact).where(
            CorporateBillingContact.account_id == account_id,
            CorporateBillingContact.email == normalised_email,
        )
    )
    if dup_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A billing contact with email '{normalised_email}' already exists in this account.",
        )

    contact = CorporateBillingContact(
        account_id=account_id,
        name=data.name,
        email=normalised_email,
        phone=data.phone,
        role=data.role,
        receives_invoices=data.receives_invoices,
        receives_budget_alerts=data.receives_budget_alerts,
        receives_monthly_summary=data.receives_monthly_summary,
        is_active=True,
        added_by_id=user_id,
    )
    db.add(contact)
    await db.flush()

    return _contact_to_response(contact)


async def get_billing_contact(
    db: AsyncSession,
    account_id: int,
    contact_id: int,
) -> BillingContactResponse:
    """Return a single billing contact.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        contact_id: Billing contact identifier.

    Returns:
        BillingContactResponse.

    Raises:
        HTTP 404: When the contact is not found in this account.
    """
    contact = await _get_contact(db, account_id, contact_id)
    return _contact_to_response(contact)


async def list_billing_contacts(
    db: AsyncSession,
    account_id: int,
    active_only: bool = True,
    skip: int = 0,
    limit: int = 50,
) -> BillingContactListResponse:
    """Return a paginated list of billing contacts for the account.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        active_only: When True, only return is_active=True contacts.
        skip: Pagination offset.
        limit: Maximum rows to return.

    Returns:
        BillingContactListResponse with total count and page of results.
    """
    q = select(CorporateBillingContact).where(
        CorporateBillingContact.account_id == account_id
    )
    if active_only:
        q = q.where(CorporateBillingContact.is_active.is_(True))

    total_result = await db.execute(
        select(func.count()).select_from(q.subquery())
    )
    total = total_result.scalar_one() or 0

    page_result = await db.execute(
        q.order_by(CorporateBillingContact.name).offset(skip).limit(limit)
    )
    contacts: Sequence[CorporateBillingContact] = page_result.scalars().all()

    return BillingContactListResponse(
        account_id=account_id,
        total=total,
        contacts=[_contact_to_response(c) for c in contacts],
    )


async def update_billing_contact(
    db: AsyncSession,
    account_id: int,
    contact_id: int,
    user_id: int,
    data: BillingContactUpdate,
) -> BillingContactResponse:
    """Update a billing contact's details (admin only).

    The email address is immutable and cannot be changed after creation.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        contact_id: Billing contact to update.
        user_id: ID of the requesting admin.
        data: Fields to update (all optional).

    Returns:
        Updated BillingContactResponse.

    Raises:
        HTTP 403: When the user is not an account admin.
        HTTP 404: When the contact is not found in this account.
    """
    await _require_admin(db, account_id, user_id)
    contact = await _get_contact(db, account_id, contact_id)

    if data.name is not None:
        contact.name = data.name
    if data.phone is not None:
        contact.phone = data.phone
    if data.role is not None:
        contact.role = data.role
    if data.receives_invoices is not None:
        contact.receives_invoices = data.receives_invoices
    if data.receives_budget_alerts is not None:
        contact.receives_budget_alerts = data.receives_budget_alerts
    if data.receives_monthly_summary is not None:
        contact.receives_monthly_summary = data.receives_monthly_summary

    await db.flush()
    return _contact_to_response(contact)


async def deactivate_billing_contact(
    db: AsyncSession,
    account_id: int,
    contact_id: int,
    user_id: int,
) -> BillingContactResponse:
    """Soft-delete a billing contact (admin only).

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        contact_id: Billing contact to deactivate.
        user_id: ID of the requesting admin.

    Returns:
        Updated BillingContactResponse with is_active=False.

    Raises:
        HTTP 403: When the user is not an account admin.
        HTTP 404: When the contact is not found in this account.
        HTTP 409: When the contact is already inactive.
    """
    await _require_admin(db, account_id, user_id)
    contact = await _get_contact(db, account_id, contact_id)

    if not contact.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Billing contact is already inactive.",
        )

    contact.is_active = False
    await db.flush()
    return _contact_to_response(contact)


async def list_contacts_for_notification(
    db: AsyncSession,
    account_id: int,
    notification_type: Literal["invoices", "budget_alerts", "monthly_summary"],
) -> list[CorporateBillingContact]:
    """Return active contacts opted-in for a specific notification type.

    Used internally by notification dispatch — not exposed via HTTP.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        notification_type: One of ``"invoices"``, ``"budget_alerts"``, or
            ``"monthly_summary"``.

    Returns:
        List of active CorporateBillingContact rows opted-in for the requested
        notification type.
    """
    flag_map = {
        "invoices": CorporateBillingContact.receives_invoices,
        "budget_alerts": CorporateBillingContact.receives_budget_alerts,
        "monthly_summary": CorporateBillingContact.receives_monthly_summary,
    }
    opt_in_col = flag_map[notification_type]

    result = await db.execute(
        select(CorporateBillingContact).where(
            CorporateBillingContact.account_id == account_id,
            CorporateBillingContact.is_active.is_(True),
            opt_in_col.is_(True),
        )
    )
    return list(result.scalars().all())
