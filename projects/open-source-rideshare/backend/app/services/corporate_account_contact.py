"""Service functions for corporate account contacts.

Enterprise accounts can register non-billing operational contacts —
the people the platform can reach for account issues, travel policy
questions, employee onboarding, and legal/compliance matters.

Public API
----------
create_contact         — register a new contact; enforces email uniqueness
get_contact            — fetch one contact by id within an account
list_contacts          — paginated list, optional role/active filters
update_contact         — partial update; maintains email uniqueness invariant
deactivate_contact     — soft-delete (sets is_active=False)
delete_contact         — hard delete
get_primary_contact    — return the is_primary contact or None
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_account_contact import (
    ContactRole,
    CorporateAccountContact,
)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _get_contact_or_404(
    db: AsyncSession, account_id: int, contact_id: int
) -> CorporateAccountContact:
    """Return the contact for *contact_id* within *account_id*; raise 404 if
    it does not exist or belongs to a different account."""
    result = await db.execute(
        select(CorporateAccountContact).where(
            CorporateAccountContact.id == contact_id,
            CorporateAccountContact.account_id == account_id,
        )
    )
    contact = result.scalar_one_or_none()
    if contact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contact not found.",
        )
    return contact


async def _clear_existing_primary(db: AsyncSession, account_id: int) -> None:
    """Unset is_primary on any existing primary contact for *account_id*."""
    result = await db.execute(
        select(CorporateAccountContact).where(
            CorporateAccountContact.account_id == account_id,
            CorporateAccountContact.is_primary.is_(True),
        )
    )
    existing_primary = result.scalar_one_or_none()
    if existing_primary is not None:
        existing_primary.is_primary = False


async def _check_duplicate_email(
    db: AsyncSession,
    account_id: int,
    email: str,
    exclude_id: Optional[int] = None,
) -> None:
    """Raise 409 if *email* already belongs to another contact on *account_id*.

    Pass *exclude_id* to allow the contact being updated to keep its own email.
    """
    query = select(CorporateAccountContact).where(
        CorporateAccountContact.account_id == account_id,
        CorporateAccountContact.email == email,
    )
    if exclude_id is not None:
        query = query.where(CorporateAccountContact.id != exclude_id)

    result = await db.execute(query)
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A contact with this email address already exists on the account.",
        )


# ---------------------------------------------------------------------------
# Public service API
# ---------------------------------------------------------------------------


async def create_contact(
    db: AsyncSession,
    account_id: int,
    name: str,
    email: str,
    phone: Optional[str],
    title: Optional[str],
    contact_role: ContactRole,
    notes: Optional[str],
    is_primary: bool,
    added_by_id: int,
) -> CorporateAccountContact:
    """Register a new operational contact for *account_id*.

    The email address is normalised to lowercase before storage.  A 409 is
    raised if the normalised email is already registered on this account.  When
    *is_primary* is True any existing primary contact is demoted first.
    """
    normalised_email = email.lower()

    await _check_duplicate_email(db, account_id, normalised_email)

    if is_primary:
        await _clear_existing_primary(db, account_id)

    contact = CorporateAccountContact(
        account_id=account_id,
        name=name,
        email=normalised_email,
        phone=phone,
        title=title,
        contact_role=contact_role,
        notes=notes,
        is_primary=is_primary,
        added_by_id=added_by_id,
    )
    db.add(contact)
    await db.flush()
    return contact


async def get_contact(
    db: AsyncSession, account_id: int, contact_id: int
) -> CorporateAccountContact:
    """Return a single contact; raises 404 if not found or wrong account."""
    return await _get_contact_or_404(db, account_id, contact_id)


async def list_contacts(
    db: AsyncSession,
    account_id: int,
    role: Optional[ContactRole] = None,
    active_only: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> list[CorporateAccountContact]:
    """Return paginated contacts for *account_id*.

    By default only active contacts are returned.  Pass *active_only=False* to
    include deactivated contacts.  Optionally filter by *role*.
    """
    query = (
        select(CorporateAccountContact)
        .where(CorporateAccountContact.account_id == account_id)
        .order_by(CorporateAccountContact.id)
        .limit(limit)
        .offset(offset)
    )

    if active_only:
        query = query.where(CorporateAccountContact.is_active.is_(True))

    if role is not None:
        query = query.where(CorporateAccountContact.contact_role == role)

    result = await db.execute(query)
    return list(result.scalars().all())


async def update_contact(
    db: AsyncSession,
    account_id: int,
    contact_id: int,
    **kwargs: Any,
) -> CorporateAccountContact:
    """Partially update a contact.

    Only keys present in *kwargs* are applied.  The email is re-normalised to
    lowercase if changed.  Raises 409 on duplicate email, 404 if not found.
    When promoting to primary any existing primary contact is demoted first.
    """
    contact = await _get_contact_or_404(db, account_id, contact_id)

    if "email" in kwargs and kwargs["email"] is not None:
        kwargs["email"] = kwargs["email"].lower()
        await _check_duplicate_email(
            db, account_id, kwargs["email"], exclude_id=contact_id
        )

    if kwargs.get("is_primary"):
        await _clear_existing_primary(db, account_id)

    for field, value in kwargs.items():
        if value is not None or field in ("notes", "phone", "title"):
            setattr(contact, field, value)

    await db.flush()
    return contact


async def deactivate_contact(
    db: AsyncSession, account_id: int, contact_id: int
) -> CorporateAccountContact:
    """Soft-delete a contact by setting is_active=False.

    Raises 404 if the contact does not exist or belongs to a different account.
    """
    contact = await _get_contact_or_404(db, account_id, contact_id)
    contact.is_active = False
    await db.flush()
    return contact


async def delete_contact(
    db: AsyncSession, account_id: int, contact_id: int
) -> None:
    """Hard-delete a contact row.

    Raises 404 if the contact does not exist or belongs to a different account.
    """
    contact = await _get_contact_or_404(db, account_id, contact_id)
    await db.delete(contact)
    await db.flush()


async def get_primary_contact(
    db: AsyncSession, account_id: int
) -> Optional[CorporateAccountContact]:
    """Return the primary contact for *account_id*, or None if none is set."""
    result = await db.execute(
        select(CorporateAccountContact).where(
            CorporateAccountContact.account_id == account_id,
            CorporateAccountContact.is_primary.is_(True),
        )
    )
    return result.scalar_one_or_none()
